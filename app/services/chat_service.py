"""聊天与会话总结业务服务。

实现多轮对话上下文组装、流式/非流式调用、轮数提醒与自动总结。
所有模型调用统一走 LangChain ChatModel 抽象层。
"""

from typing import Any, AsyncIterator, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.context import get_current_user_id
from app.core.exceptions import BusinessError, NotFoundError
from app.core.logger import get_logger
from app.db.mysql.models.conversation import Conversation
from app.db.mysql.models.message import Message, MessageRole
from app.db.redis import CACHE_PREFIX_STREAM_STATE, RedisCache
from app.schemas.request.chat import ChatInvokeRequest, ConversationCreateRequest
from app.schemas.response.chat import ChatInvokeResponse
from app.services.conversation_service import ConversationService
from app.services.knowledge_service import KnowledgeService
from app.services.llm import ollama as _ollama  # noqa: F401  触发注册
from app.services.llm import openai_compatible as _openai  # noqa: F401  触发注册
from app.services.llm.base import LLMFactory, ainvoke_chat, astream_chat
from app.services.model_service import ModelService
from app.services.prompt_service import PromptService
from app.utils.token_counter import token_counter

log = get_logger("services.chat")

# 会话总结提示词
_SUMMARY_SYSTEM_PROMPT = (
    "你是一个对话摘要助手。请将以下历史对话浓缩为精简摘要，"
    "保留关键事实、用户意图、已达成结论与待办事项，使用简洁中文输出。"
)


class ChatService:
    """对话业务核心服务。"""

    def __init__(self, db: Session) -> None:
        self.db = db
        self.settings = get_settings()
        self.model_service = ModelService(db)
        self.prompt_service = PromptService(db)
        self.conversation_service = ConversationService(db)
        self.knowledge_service = KnowledgeService(db)
        self.cache = RedisCache()

    # -------------------- 公共入口 --------------------

    async def invoke(self, req: ChatInvokeRequest) -> ChatInvokeResponse:
        """非流式问答。

        Args:
            req: 问答请求

        Returns:
            完整回答与会话状态
        """
        conversation, model_row, messages = await self._prepare_context(req)
        chat_model = LLMFactory.create_from_model_row(
            model_row,
            temperature=req.temperature,
            max_tokens=req.max_tokens,
        )

        try:
            answer = await ainvoke_chat(chat_model, messages)
        except Exception as e:
            log.exception(f"非流式调用失败: conversation_id={conversation.id}, error={e}")
            raise BusinessError(f"模型调用失败: {e}") from e

        assistant_msg, summary_triggered = self._persist_turn(
            conversation=conversation,
            user_content=req.message,
            assistant_content=answer,
            model_max_context=model_row.max_context,
        )

        # 若触发总结，在回答后再执行（避免阻塞首响时可改为异步任务）
        if summary_triggered:
            await self._run_summary(conversation, model_row)

        is_warn = conversation.round_count >= self.settings.round_warn_threshold
        return ChatInvokeResponse(
            conversation_id=conversation.id,
            message_id=assistant_msg.id,
            content=answer,
            round_count=conversation.round_count,
            is_warn_round=is_warn,
            summary_triggered=summary_triggered,
        )

    async def stream(self, req: ChatInvokeRequest) -> AsyncIterator[dict[str, Any]]:
        """流式问答（SSE 事件字典生成器）。

        Yields:
            {"event": "chunk|done|error", "data": {...}}
        """
        try:
            conversation, model_row, messages = await self._prepare_context(req)
            chat_model = LLMFactory.create_from_model_row(
                model_row,
                temperature=req.temperature,
                max_tokens=req.max_tokens,
            )

            # 预占位：先写入用户消息，助手消息在结束后写入
            user_msg = self._save_message(
                conversation_id=conversation.id,
                role=MessageRole.USER,
                content=req.message,
            )
            full_answer = ""

            # 缓存流式会话状态（预留）
            self.cache.set_json(
                f"{CACHE_PREFIX_STREAM_STATE}{conversation.id}",
                {"status": "streaming", "user_message_id": user_msg.id},
                ttl=600,
            )

            async for chunk in astream_chat(chat_model, messages):
                full_answer += chunk
                yield {
                    "event": "chunk",
                    "data": {
                        "content": chunk,
                        "conversation_id": conversation.id,
                        "message_id": None,  # 结束后才有正式 ID
                    },
                }

            assistant_msg = self._save_message(
                conversation_id=conversation.id,
                role=MessageRole.ASSISTANT,
                content=full_answer,
            )
            conversation.round_count += 1
            # 首轮自动用用户消息截断作为标题
            if conversation.round_count == 1 and conversation.title == "新会话":
                conversation.title = req.message[:50]
            self.db.commit()
            self.db.refresh(conversation)

            summary_triggered = self._need_summary(conversation, model_row.max_context)
            if summary_triggered:
                await self._run_summary(conversation, model_row)

            self.cache.delete(f"{CACHE_PREFIX_STREAM_STATE}{conversation.id}")

            yield {
                "event": "done",
                "data": {
                    "conversation_id": conversation.id,
                    "message_id": assistant_msg.id,
                    "round_count": conversation.round_count,
                    "is_warn_round": conversation.round_count
                    >= self.settings.round_warn_threshold,
                    "summary_triggered": summary_triggered,
                },
            }
        except Exception as e:
            log.exception(f"流式调用失败: {e}")
            yield {
                "event": "error",
                "data": {"code": 500, "message": str(e)},
            }

    async def trigger_summary(self, conversation_id: int) -> Conversation:
        """用户主动触发会话总结。"""
        conversation = self.conversation_service.get_owned_orm(conversation_id)
        model_row = self.model_service.get_chat_model_orm(conversation.model_id)
        await self._run_summary(conversation, model_row)
        self.db.refresh(conversation)
        return conversation

    # -------------------- 上下文准备 --------------------

    async def _prepare_context(
        self,
        req: ChatInvokeRequest,
    ) -> tuple[Conversation, Any, list[dict[str, str]]]:
        """准备会话、模型与拼装后的消息上下文。

        Returns:
            (conversation, model_row, messages)
        """
        model_row = self.model_service.get_chat_model_orm(req.model_id)
        if model_row.status != 1:
            raise BusinessError("模型已禁用，无法调用")

        # 会话：为空则自动创建
        if req.conversation_id:
            conversation = self.conversation_service.get_owned_orm(req.conversation_id)
            # 允许切换模型：以请求中的 model_id 为准更新绑定
            if conversation.model_id != req.model_id:
                conversation.model_id = req.model_id
                self.db.commit()
        else:
            conversation = self.conversation_service.create(
                ConversationCreateRequest(
                    title="新会话",
                    model_id=req.model_id,
                )
            )
            # create 返回的是 Response，需重新取 ORM
            conversation = self.conversation_service.get_owned_orm(conversation.id)

        messages = self._build_messages(conversation, req)
        return conversation, model_row, messages

    def _build_messages(
        self,
        conversation: Conversation,
        req: ChatInvokeRequest,
    ) -> list[dict[str, str]]:
        """按规则组装上下文：system(模板/总结) + 历史 + 当前用户消息。"""
        messages: list[dict[str, str]] = []

        # 1) 提示词模板作为 system prompt
        if req.prompt_template_id:
            try:
                rendered = self.prompt_service.get_rendered_content(
                    req.prompt_template_id,
                    req.prompt_variables,
                )
                messages.append({"role": "system", "content": rendered})
            except NotFoundError:
                log.warning(f"提示词模板不存在: id={req.prompt_template_id}")

        # 1.5) 知识库 RAG 检索注入
        if req.knowledge_base_id:
            try:
                hits = self.knowledge_service.retrieve_for_rag(
                    req.knowledge_base_id,
                    req.message,
                    top_k=req.rag_top_k,
                )
                rag_text = KnowledgeService.format_rag_context(hits)
                if rag_text:
                    messages.append({"role": "system", "content": rag_text})
                    log.info(
                        f"RAG 注入成功: kb_id={req.knowledge_base_id}, hits={len(hits)}"
                    )
                else:
                    log.info(f"RAG 无命中: kb_id={req.knowledge_base_id}")
            except Exception as e:
                log.warning(f"RAG 检索失败，将忽略知识库: {e}")

        # 2) 会话历史总结注入
        if conversation.summary:
            messages.append(
                {
                    "role": "system",
                    "content": f"以下是此前对话的摘要，请据此保持上下文连贯：\n{conversation.summary}",
                }
            )

        # 3) 加载历史消息（时间正序）；若已有总结则只保留最近 N 轮
        history = self.db.scalars(
            select(Message)
            .where(Message.conversation_id == conversation.id)
            .order_by(Message.id.asc())
        ).all()

        if conversation.summary:
            # 每轮 = user + assistant 两条，保留最近 keep_rounds 轮
            keep_msgs = self.settings.summary_keep_rounds * 2
            history = history[-keep_msgs:] if keep_msgs > 0 else history

        for m in history:
            role = m.role.value if hasattr(m.role, "value") else str(m.role)
            # system 消息不重复注入历史（总结已单独处理）
            if role == "system":
                continue
            messages.append({"role": role, "content": m.content})

        # 4) 当前用户消息
        messages.append({"role": "user", "content": req.message})
        return messages

    # -------------------- 持久化与总结 --------------------

    def _persist_turn(
        self,
        *,
        conversation: Conversation,
        user_content: str,
        assistant_content: str,
        model_max_context: int,
    ) -> tuple[Message, bool]:
        """保存一轮对话并更新会话轮数，返回助手消息与是否需总结。"""
        self._save_message(conversation.id, MessageRole.USER, user_content)
        assistant_msg = self._save_message(
            conversation.id, MessageRole.ASSISTANT, assistant_content
        )
        conversation.round_count += 1
        if conversation.round_count == 1 and conversation.title == "新会话":
            conversation.title = user_content[:50]
        self.db.commit()
        self.db.refresh(conversation)
        self.db.refresh(assistant_msg)

        need = self._need_summary(conversation, model_max_context)
        return assistant_msg, need

    def _save_message(
        self,
        conversation_id: int,
        role: MessageRole,
        content: str,
    ) -> Message:
        """写入单条消息。"""
        user_id = get_current_user_id()
        msg = Message(
            conversation_id=conversation_id,
            user_id=user_id,
            role=role,
            content=content,
            token_count=token_counter.count_text(content),
        )
        self.db.add(msg)
        self.db.commit()
        self.db.refresh(msg)
        return msg

    def _need_summary(self, conversation: Conversation, max_context: int) -> bool:
        """判断是否满足自动总结触发条件。"""
        if conversation.round_count >= self.settings.summary_trigger_rounds:
            return True
        # 按 token 占用比例判断
        history = self.db.scalars(
            select(Message)
            .where(Message.conversation_id == conversation.id)
            .order_by(Message.id.asc())
        ).all()
        msgs = [
            {"role": m.role.value if hasattr(m.role, "value") else str(m.role), "content": m.content}
            for m in history
        ]
        return token_counter.should_trigger_summary(
            msgs,
            max_context,
            ratio=self.settings.summary_token_ratio,
        )

    async def _run_summary(self, conversation: Conversation, model_row: Any) -> None:
        """执行会话总结：浓缩历史并保留最近 N 轮。

        总结结果写入 conversation.summary，旧长历史仍保留在 messages 表
        （便于审计），上下文组装时仅使用 summary + 最近 N 轮。
        """
        history = self.db.scalars(
            select(Message)
            .where(Message.conversation_id == conversation.id)
            .order_by(Message.id.asc())
        ).all()
        if not history:
            return

        # 需要被总结的部分：去掉最近 keep_rounds 轮
        keep = self.settings.summary_keep_rounds * 2
        to_summarize = history[:-keep] if keep < len(history) else history
        if not to_summarize:
            return

        dialog_text = "\n".join(
            f"{m.role.value if hasattr(m.role, 'value') else m.role}: {m.content}"
            for m in to_summarize
        )
        # 若已有旧摘要，一并纳入
        if conversation.summary:
            dialog_text = f"旧摘要：\n{conversation.summary}\n\n新对话：\n{dialog_text}"

        chat_model = LLMFactory.create_from_model_row(model_row, temperature=0.3)
        summary_messages = [
            {"role": "system", "content": _SUMMARY_SYSTEM_PROMPT},
            {"role": "user", "content": dialog_text},
        ]
        try:
            summary = await ainvoke_chat(chat_model, summary_messages)
            conversation.summary = summary
            self.db.commit()
            log.info(
                f"会话总结完成: conversation_id={conversation.id}, "
                f"rounds={conversation.round_count}"
            )
        except Exception as e:
            log.exception(f"会话总结失败: conversation_id={conversation.id}, error={e}")
            # 总结失败不阻断主流程
            self.db.rollback()
