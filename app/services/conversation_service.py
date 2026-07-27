"""会话管理业务服务。"""

from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.context import get_current_user_id
from app.core.exceptions import NotFoundError
from app.core.logger import get_logger
from app.db.mysql.models.conversation import Conversation
from app.db.mysql.models.message import Message
from app.schemas.request.chat import ConversationCreateRequest, ConversationUpdateRequest
from app.schemas.response.chat import ConversationResponse, MessageResponse
from app.schemas.response.common import PageResult

log = get_logger("services.conversation")


class ConversationService:
    """会话 CRUD 与消息历史查询。"""

    def __init__(self, db: Session) -> None:
        self.db = db

    def _to_response(
        self,
        row: Conversation,
        messages: Optional[list[Message]] = None,
    ) -> ConversationResponse:
        resp = ConversationResponse.model_validate(row)
        if messages is not None:
            resp.messages = [MessageResponse.model_validate(m) for m in messages]
        return resp

    def create(self, req: ConversationCreateRequest) -> ConversationResponse:
        """新建会话。"""
        user_id = get_current_user_id()
        row = Conversation(
            user_id=user_id,
            title=req.title,
            model_id=req.model_id,
            round_count=0,
            summary=None,
        )
        self.db.add(row)
        self.db.commit()
        self.db.refresh(row)
        log.info(f"新建会话: id={row.id}, user_id={user_id}")
        return self._to_response(row)

    def list_conversations(
        self,
        page: int = 1,
        page_size: int = 20,
    ) -> PageResult[ConversationResponse]:
        """分页获取当前用户会话列表。"""
        user_id = get_current_user_id()
        page = max(1, page)
        page_size = min(max(1, page_size), 100)

        total = self.db.scalar(
            select(func.count()).select_from(Conversation).where(Conversation.user_id == user_id)
        ) or 0

        stmt = (
            select(Conversation)
            .where(Conversation.user_id == user_id)
            .order_by(Conversation.update_time.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        rows = self.db.scalars(stmt).all()
        return PageResult(
            items=[self._to_response(r) for r in rows],
            total=total,
            page=page,
            page_size=page_size,
        )

    def get_conversation(
        self,
        conversation_id: int,
        *,
        with_messages: bool = True,
        msg_page: int = 1,
        msg_page_size: int = 100,
    ) -> ConversationResponse:
        """获取会话详情（可选附带历史消息）。"""
        row = self._get_owned(conversation_id)
        messages = None
        if with_messages:
            messages = self.list_messages(
                conversation_id,
                page=msg_page,
                page_size=msg_page_size,
            )
        return self._to_response(row, messages=messages)

    def update_title(
        self,
        conversation_id: int,
        req: ConversationUpdateRequest,
    ) -> ConversationResponse:
        """修改会话标题。"""
        row = self._get_owned(conversation_id)
        row.title = req.title
        self.db.commit()
        self.db.refresh(row)
        log.info(f"修改会话标题: id={conversation_id}, title={req.title}")
        return self._to_response(row)

    def delete(self, conversation_id: int) -> None:
        """删除会话及其全部消息。"""
        row = self._get_owned(conversation_id)
        # 先删消息再删会话
        msgs = self.db.scalars(
            select(Message).where(Message.conversation_id == conversation_id)
        ).all()
        for m in msgs:
            self.db.delete(m)
        self.db.delete(row)
        self.db.commit()
        log.info(f"删除会话: id={conversation_id}, 消息数={len(msgs)}")

    def list_messages(
        self,
        conversation_id: int,
        page: int = 1,
        page_size: int = 100,
    ) -> list[Message]:
        """分页查询指定会话消息（仅限本人会话）。"""
        self._get_owned(conversation_id)
        page = max(1, page)
        page_size = min(max(1, page_size), 500)
        stmt = (
            select(Message)
            .where(Message.conversation_id == conversation_id)
            .order_by(Message.id.asc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        return list(self.db.scalars(stmt).all())

    def count_by_user(self, user_id: Optional[str] = None) -> int:
        """统计用户会话总数。"""
        uid = user_id or get_current_user_id()
        return self.db.scalar(
            select(func.count()).select_from(Conversation).where(Conversation.user_id == uid)
        ) or 0

    def _get_owned(self, conversation_id: int) -> Conversation:
        """获取当前用户所属会话，越权返回不存在。"""
        user_id = get_current_user_id()
        row = self.db.get(Conversation, conversation_id)
        if row is None or row.user_id != user_id:
            raise NotFoundError("会话不存在")
        return row

    def get_owned_orm(self, conversation_id: int) -> Conversation:
        """供 ChatService 内部使用。"""
        return self._get_owned(conversation_id)
