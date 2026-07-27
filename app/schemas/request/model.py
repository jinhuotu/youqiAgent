"""模型管理相关请求 Schema。"""

from typing import Optional

from pydantic import BaseModel, Field

from app.db.mysql.models.model_config import ModelScope, ModelType


class ModelCreateRequest(BaseModel):
    """新增模型配置请求。"""

    name: str = Field(..., min_length=1, max_length=128, description="模型展示名称")
    type: ModelType = Field(..., description="模态类型")
    provider: str = Field(
        default="openai_compatible",
        max_length=64,
        description="提供商标识：openai_compatible/ollama/deepseek/zhipu",
    )
    base_url: str = Field(..., min_length=1, max_length=512, description="接口地址")
    api_key: str = Field(default="", description="API密钥")
    model_id: str = Field(..., min_length=1, max_length=128, description="模型标识符")
    max_context: int = Field(default=8192, ge=512, le=1000000, description="最大上下文长度")
    scope: ModelScope = Field(default=ModelScope.PRIVATE, description="作用域")
    status: int = Field(default=1, ge=0, le=1, description="1启用 0禁用")


class ModelUpdateRequest(BaseModel):
    """修改模型配置请求（部分更新）。"""

    name: Optional[str] = Field(default=None, min_length=1, max_length=128)
    type: Optional[ModelType] = None
    provider: Optional[str] = Field(default=None, max_length=64)
    base_url: Optional[str] = Field(default=None, max_length=512)
    api_key: Optional[str] = None
    model_id: Optional[str] = Field(default=None, max_length=128)
    max_context: Optional[int] = Field(default=None, ge=512, le=1000000)
    scope: Optional[ModelScope] = None
    status: Optional[int] = Field(default=None, ge=0, le=1)
