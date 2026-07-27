"""会话与聊天相关响应 Schema。"""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from app.db.mysql.models.message import MessageRole


class MessageResponse(BaseModel):
    """单条消息响应。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    conversation_id: int
    role: MessageRole
    content: str
    token_count: int = 0
    create_time: Optional[datetime] = None


class ConversationResponse(BaseModel):
    """会话详情响应。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: str
    title: str
    model_id: int
    round_count: int
    summary: Optional[str] = None
    create_time: Optional[datetime] = None
    update_time: Optional[datetime] = None
    messages: Optional[list[MessageResponse]] = Field(
        default=None,
        description="历史消息（详情接口返回）",
    )


class ChatInvokeResponse(BaseModel):
    """非流式问答响应。"""

    conversation_id: int
    message_id: int
    content: str = Field(..., description="助手完整回复")
    round_count: int
    is_warn_round: bool = Field(default=False, description="是否超过轮数提醒阈值")
    summary_triggered: bool = Field(default=False, description="本次是否触发了自动总结")
