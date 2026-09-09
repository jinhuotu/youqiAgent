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
from app.schemas.response.chat import ChatInvokeResponse, RagSourceItem
from app.services.conversation_service import ConversationService
from app.services.knowledge_service import KnowledgeService
from app.services.llm import ollama as _ollama  # noqa: F401  触发注册
from app.services.llm import openai_compatible as _openai  # noqa: F401  触发注册
from app.services.llm.base import LLMFactory, ainvoke_chat, astream_chat
from app.services.mcp_server_service import McpServerService
from app.services.mcp_tool_adapter import build_langchain_tools
from app.services.model_service import ModelService
from app.services.prompt_service import PromptService
from app.services.tool_loop import DisconnectChecker, run_tool_loop
from app.utils.dsml import strip_tool_call_markup
from app.utils.token_counter import token_counter

log = get_logger("services.chat")

# DisconnectChecker 从 tool_loop 导入，保持类型一致

# 会话总结提示词
_SUMMARY_SYSTEM_PROMPT = (
    "你是一个对话摘要助手。请将以下历史对话浓缩为精简摘要，"
    "保留关键事实、用户意图、已达成结论与待办事项，使用简洁中文输出。"
)


def _public_llm_error(exc: Exception) -> str:
    """对外暴露的精简错误信息，避免泄露上游细节。"""
    text = str(exc).strip()
    lowered = text.lower()
    if "reasoning_content" in lowered:
        return (
            "模型 thinking 模式要求回传推理内容，当前多轮工具调用未带上该字段。"
            "不是余额问题。请重启已关闭 thinking 的后端后重试；"
            "若需开启思考，设置 LLM_ENABLE_THINKING=true 并确保助手消息回传 reasoning_content"
        )
    status = getattr(exc, "status_code", None)
    if status is not None:
        return f"模型服务调用失败（HTTP {status}），请检查模型配置、密钥与额度后重试"
    text = str(exc).strip()
    if not text:
        return "模型调用失败，请稍后重试"
    # 截断过长的 SDK/堆栈片段
    if len(text) > 160:
        text = text[:160] + "…"
    if "api_key" in text.lower() or "authorization" in text.lower():
        return "模型鉴权失败，请检查模型 API Key 配置"
    lowered = text.lower()
    if "connection error" in lowered or "connecterror" in lowered or "all connection attempts failed" in lowered:
        return (
            "无法连接模型 API（不是网页版 chat.deepseek.com）。"
            "请确认模型管理里的 base_url/API Key，并检查本机代理；"
            "可在 .env 设置 LLM_HTTP_TRUST_ENV=false 后重启后端再试"
        )
    return f"模型调用失败: {text}"


def _client_visible_text(text: str) -> str:
    """发给调用方的正文不得包含 DSML/工具标记。"""
    return strip_tool_call_markup(text or "")


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
        conversation, model_row, messages, rag_sources = await self._prepare_context(req)
        chat_model = LLMFactory.create_from_model_row(
            model_row,
            temperature=req.temperature,
            max_tokens=req.max_tokens,
        )

        try:
            tools = self._resolve_mcp_tools(req)
            if tools:
                answer = ""
                async for item in run_tool_loop(chat_model, messages, tools):
                    if item.get("event") == "final":
                        data = item.get("data") or {}
                        if data.get("skipped"):
                            answer = _client_visible_text(
                                await ainvoke_chat(chat_model, messages)
                            )
                        else:
                            answer = _client_visible_text(str(data.get("content") or ""))
                if not answer and tools:
                    # tool loop 无最终文本时回退
                    answer = _client_visible_text(
                        await ainvoke_chat(chat_model, messages)
                    )
            else:
                answer = _client_visible_text(await ainvoke_chat(chat_model, messages))
        except Exception as e:
            log.exception(f"非流式调用失败: conversation_id={conversation.id}, error={e}")
            raise BusinessError(_public_llm_error(e)) from e

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
            sources=[RagSourceItem(**s) for s in rag_sources],
        )

    async def stream(
        self,
        req: ChatInvokeRequest,
        *,
        is_disconnected: Optional[DisconnectChecker] = None,
    ) -> AsyncIterator[dict[str, Any]]:
        """流式问答（SSE 事件字典生成器）。

        Yields:
            {"event": "sources|chunk|done|error", "data": {...}}
        """
        conversation: Optional[Conversation] = None
        full_answer = ""
        user_saved = False
        stream_key: Optional[str] = None
        cancelled = False
        try:
            conversation, model_row, messages, rag_sources = await self._prepare_context(
                req, run_rag=False
            )
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
            user_saved = True
            stream_key = f"{CACHE_PREFIX_STREAM_STATE}{conversation.id}"

            # 缓存流式会话状态
            self.cache.set_json(
                stream_key,
                {"status": "streaming", "user_message_id": user_msg.id},
                ttl=600,
            )

            yield {
                "event": "status",
                "data": {
                    "message": "正在处理…",
                    "conversation_id": conversation.id,
                },
            }

            if req.knowledge_base_id:
                yield {
                    "event": "status",
                    "data": {
                        "message": "正在检索知识库…",
                        "conversation_id": conversation.id,
                    },
                }
                rag_messages, rag_sources = self._rag_system_messages(req)
                insert_at = 1 if messages and messages[0].get("role") == "system" else 0
                for i, item in enumerate(rag_messages):
                    messages.insert(insert_at + i, item)

            if rag_sources:
                yield {
                    "event": "sources",
                    "data": {
                        "conversation_id": conversation.id,
                        "sources": rag_sources,
                    },
                }

            tools = self._resolve_mcp_tools(req)
            if tools:
                yield {
                    "event": "status",
                    "data": {
                        "message": "正在查询业务数据…",
                        "conversation_id": conversation.id,
                    },
                }
                async for item in run_tool_loop(
                    chat_model,
                    messages,
                    tools,
                    is_disconnected=is_disconnected,
                ):
                    event = item.get("event")
                    data = item.get("data") or {}
                    if event in ("tool_call", "tool_result", "status"):
                        yield {
                            "event": event,
                            "data": {
                                **data,
                                "conversation_id": conversation.id,
                            },
                        }
                    elif event == "final":
                        if data.get("cancelled"):
                            cancelled = True
                            full_answer = _client_visible_text(
                                str(data.get("content") or full_answer)
                            )
                            break
                        if data.get("skipped"):
                            async for chunk in astream_chat(chat_model, messages):
                                if is_disconnected is not None and await is_disconnected():
                                    cancelled = True
                                    break
                                full_answer += chunk
                                yield {
                                    "event": "chunk",
                                    "data": {
                                        "content": chunk,
                                        "conversation_id": conversation.id,
                                        "message_id": None,
                                    },
                                }
                            full_answer = _client_visible_text(full_answer)
                        else:
                            text = _client_visible_text(str(data.get("content") or ""))
                            if text:
                                full_answer = text
                                yield {
                                    "event": "chunk",
                                    "data": {
                                        "content": text,
                                        "conversation_id": conversation.id,
                                        "message_id": None,
                                    },
                                }
                if cancelled:
                    pass  # fall through to cancelled save below
                elif not full_answer:
                    # 工具路径已跑完仍无正文：不要再卡一轮 LLM，避免页面一直转
                    full_answer = (
                        "当前没有可展示的查询结果。"
                        "若是查库问题，请确认 MCP 已配置库中是否存在对应表。"
                    )
                    yield {
                        "event": "chunk",
                        "data": {
                            "content": full_answer,
                            "conversation_id": conversation.id,
                            "message_id": None,
                        },
                    }
            else:
                async for chunk in astream_chat(chat_model, messages):
                    if is_disconnected is not None and await is_disconnected():
                        cancelled = True
                        log.info(
                            f"检测到客户端断开，停止流式生成: conversation_id={conversation.id}"
                        )
                        break
                    full_answer += chunk
                    yield {
                        "event": "chunk",
                        "data": {
                            "content": chunk,
                            "conversation_id": conversation.id,
                            "message_id": None,
                        },
                    }

            if cancelled:
                full_answer = _client_visible_text(full_answer)
                assistant_content = (
                    f"{full_answer.rstrip()}\n\n（已停止生成）"
                    if full_answer.strip()
                    else "（已停止生成）"
                )
                assistant_msg = self._save_message(
                    conversation_id=conversation.id,
                    role=MessageRole.ASSISTANT,
                    content=assistant_content,
                )
                conversation.round_count += 1
                if conversation.round_count == 1 and conversation.title == "新会话":
                    conversation.title = req.message[:50]
                self.db.commit()
                self.db.refresh(conversation)
                yield {
                    "event": "done",
                    "data": {
                        "conversation_id": conversation.id,
                        "message_id": assistant_msg.id,
                        "round_count": conversation.round_count,
                        "is_warn_round": conversation.round_count
                        >= self.settings.round_warn_threshold,
                        "summary_triggered": False,
                        "cancelled": True,
                    },
                }
                return

            full_answer = _client_visible_text(full_answer)
            assistant_msg = self._save_message(
                conversation_id=conversation.id,
                role=MessageRole.ASSISTANT,
                content=full_answer,
            )
            conversation.round_count += 1
            if conversation.round_count == 1 and conversation.title == "新会话":
                conversation.title = req.message[:50]
            self.db.commit()
            self.db.refresh(conversation)

            summary_triggered = self._need_summary(conversation, model_row.max_context)
            if summary_triggered:
                await self._run_summary(conversation, model_row)

            yield {
                "event": "done",
                "data": {
                    "conversation_id": conversation.id,
                    "message_id": assistant_msg.id,
                    "round_count": conversation.round_count,
                    "is_warn_round": conversation.round_count
                    >= self.settings.round_warn_threshold,
                    "summary_triggered": summary_triggered,
                    "cancelled": False,
                },
            }
        except GeneratorExit:
            # StreamingResponse 被客户端中断时可能触发
            cancelled = True
            log.info(
                f"流式生成器被关闭: conversation_id={getattr(conversation, 'id', None)}"
            )
            if conversation is not None and user_saved:
                try:
                    assistant_content = (
                        f"{full_answer.rstrip()}\n\n（已停止生成）"
                        if full_answer.strip()
                        else "（已停止生成）"
                    )
                    self._save_message(
                        conversation.id,
                        MessageRole.ASSISTANT,
                        assistant_content,
                    )
                    conversation.round_count += 1
                    if conversation.round_count == 1 and conversation.title == "新会话":
                        conversation.title = req.message[:50]
                    self.db.commit()
                except Exception:
                    log.exception("客户端断开后补写助手消息失败")
                    try:
                        self.db.rollback()
                    except Exception:
                        pass
            raise
        except Exception as e:
            log.exception(
                f"流式调用失败: conversation_id={getattr(conversation, 'id', None)}, error={e}"
            )
            public_msg = _public_llm_error(e)
            # 用户消息已落库时，补写助手消息并推进轮数，避免脏会话
            if conversation is not None and user_saved:
                try:
                    if full_answer.strip():
                        assistant_content = f"{full_answer.rstrip()}\n\n（生成中断）{public_msg}"
                    else:
                        assistant_content = f"（生成失败）{public_msg}"
                    self._save_message(
                        conversation.id,
                        MessageRole.ASSISTANT,
                        assistant_content,
                    )
                    conversation.round_count += 1
                    if conversation.round_count == 1 and conversation.title == "新会话":
                        conversation.title = req.message[:50]
                    self.db.commit()
                except Exception:
                    log.exception("流式失败后补写助手消息失败")
                    try:
                        self.db.rollback()
                    except Exception:
                        pass
            yield {
                "event": "error",
                "data": {
                    "code": 500,
                    "message": public_msg,
                    "conversation_id": getattr(conversation, "id", None),
                    "round_count": getattr(conversation, "round_count", None),
                },
            }
        finally:
            if stream_key:
                self.cache.delete(stream_key)

    async def trigger_summary(self, conversation_id: int) -> Conversation:
        """用户主动触发会话总结。"""
        conversation = self.conversation_service.get_owned_orm(conversation_id)
        model_row = self.model_service.get_chat_model_orm(conversation.model_id)
        await self._run_summary(conversation, model_row)
        self.db.refresh(conversation)
        return conversation

    # -------------------- 上下文准备 --------------------

    def _resolve_mcp_tools(self, req: ChatInvokeRequest) -> list:
        """加载全局启用的 MCP 工具（可按 server / 工具名过滤）。"""
        try:
            bundles = McpServerService(self.db).build_tool_bundles(
                mcp_server_ids=req.mcp_server_ids,
            )
            if not bundles:
                return []
            tools = build_langchain_tools(bundles)
            if req.tool_names:
                allow = set(req.tool_names)
                tools = [t for t in tools if t.name in allow]
            if tools:
                log.info(f"已加载 MCP 工具 {len(tools)} 个")
            return tools
        except Exception as e:
            log.warning(f"加载 MCP 工具失败，将跳过工具调用: {e}")
            return []

    def _rag_system_messages(
        self,
        req: ChatInvokeRequest,
    ) -> tuple[list[dict[str, str]], list[dict[str, Any]]]:
        """检索知识库并返回待插入的 system 消息。失败时不打断对话。"""
        if not req.knowledge_base_id:
            return [], []
        try:
            hits = self.knowledge_service.retrieve_for_rag(
                req.knowledge_base_id,
                req.message,
                top_k=req.rag_top_k,
            )
            rag_text = KnowledgeService.format_rag_context(hits)
            if rag_text:
                sources = KnowledgeService.hits_to_sources(
                    hits,
                    preview_chars=self.settings.kb_source_preview_chars,
                )
                log.info(
                    f"RAG 注入成功: kb_id={req.knowledge_base_id}, hits={len(hits)}"
                )
                return [{"role": "system", "content": rag_text}], sources
            log.info(f"RAG 无命中: kb_id={req.knowledge_base_id}")
            return [
                {
                    "role": "system",
                    "content": (
                        "知识库未检索到与当前问题直接相关的资料。"
                        "请明确告知用户资料不足，不要编造维修方法或质检标准。"
                    ),
                }
            ], []
        except Exception as e:
            log.warning(f"RAG 检索失败，将忽略知识库: {e}")
            return [
                {
                    "role": "system",
                    "content": (
                        "知识库检索暂时失败。请告知用户当前无法依据知识库作答，"
                        "并建议稍后重试或补充更具体的设备/质检问题，不要编造。"
                    ),
                }
            ], []

    async def _prepare_context(
        self,
        req: ChatInvokeRequest,
        *,
        run_rag: bool = True,
    ) -> tuple[Conversation, Any, list[dict[str, str]], list[dict[str, Any]]]:
        """准备会话、模型与拼装后的消息上下文。

        Returns:
            (conversation, model_row, messages, rag_sources)
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

        messages, rag_sources = self._build_messages(conversation, req, run_rag=run_rag)
        return conversation, model_row, messages, rag_sources

    def _build_messages(
        self,
        conversation: Conversation,
        req: ChatInvokeRequest,
        *,
        run_rag: bool = True,
    ) -> tuple[list[dict[str, str]], list[dict[str, Any]]]:
        """按规则组装上下文：system(模板/总结) + 历史 + 当前用户消息。

        Returns:
            (messages, rag_sources)
        """
        messages: list[dict[str, str]] = []
        rag_sources: list[dict[str, Any]] = []

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
        if run_rag and req.knowledge_base_id:
            rag_messages, rag_sources = self._rag_system_messages(req)
            messages.extend(rag_messages)

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
        return messages, rag_sources

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
