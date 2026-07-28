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


class RagSourceItem(BaseModel):
    """RAG 引用来源（供前端展示）。"""

    id: str = Field(default="", description="向量块 ID")
    title: str = Field(default="未命名", description="文档标题")
    content: str = Field(default="", description="片段预览")
    document_id: Optional[int] = Field(default=None, description="文档 ID")
    chunk_index: Optional[int] = Field(default=None, description="块序号")
    distance: Optional[float] = Field(default=None, description="向量距离（越小越相似）")


class ChatInvokeResponse(BaseModel):
    """非流式问答响应。"""

    conversation_id: int
    message_id: int
    content: str = Field(..., description="助手完整回复")
    round_count: int
    is_warn_round: bool = Field(default=False, description="是否超过轮数提醒阈值")
    summary_triggered: bool = Field(default=False, description="本次是否触发了自动总结")
    sources: list[RagSourceItem] = Field(
        default_factory=list,
        description="本次 RAG 命中来源（未开启知识库时为空）",
    )
