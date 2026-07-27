"""会话与聊天相关请求 Schema。"""

from typing import Any, Optional

from pydantic import BaseModel, Field


class ConversationCreateRequest(BaseModel):
    """新建会话请求。"""

    title: str = Field(default="新会话", max_length=256, description="会话标题")
    model_id: int = Field(..., description="绑定模型配置ID")


class ConversationUpdateRequest(BaseModel):
    """修改会话标题请求。"""

    title: str = Field(..., min_length=1, max_length=256, description="新标题")


class ChatInvokeRequest(BaseModel):
    """非流式/流式问答公共请求体。"""

    conversation_id: Optional[int] = Field(
        default=None,
        description="会话ID，为空则自动创建新会话",
    )
    model_id: int = Field(..., description="使用的模型配置ID")
    message: str = Field(..., min_length=1, description="用户消息内容")
    prompt_template_id: Optional[int] = Field(
        default=None,
        description="提示词模板ID，可选",
    )
    prompt_variables: Optional[dict[str, Any]] = Field(
        default=None,
        description="模板变量参数，用于渲染占位符",
    )
    knowledge_base_id: Optional[int] = Field(
        default=None,
        description="知识库ID，可选；传入后对当前问题做 RAG 检索并注入上下文",
    )
    rag_top_k: Optional[int] = Field(
        default=None,
        ge=1,
        le=20,
        description="RAG 召回条数，默认取服务端配置",
    )
    temperature: float = Field(default=0.7, ge=0, le=2, description="采样温度")
    max_tokens: Optional[int] = Field(default=None, ge=1, description="最大生成 token")
