"""提示词模板相关请求 Schema。"""

from typing import Optional

from pydantic import BaseModel, Field

from app.db.mysql.models.model_config import ModelType
from app.db.mysql.models.prompt_template import TemplateScope


class PromptCreateRequest(BaseModel):
    """新增提示词模板。"""

    name: str = Field(..., min_length=1, max_length=128)
    content: str = Field(..., min_length=1, description="模板内容，支持 {var} 占位符")
    model_type: Optional[ModelType] = Field(default=None, description="适用模型类型")
    scope: TemplateScope = Field(default=TemplateScope.PRIVATE)
    description: Optional[str] = Field(default=None, max_length=512)


class PromptUpdateRequest(BaseModel):
    """编辑提示词模板。"""

    name: Optional[str] = Field(default=None, min_length=1, max_length=128)
    content: Optional[str] = Field(default=None, min_length=1)
    model_type: Optional[ModelType] = None
    scope: Optional[TemplateScope] = None
    description: Optional[str] = Field(default=None, max_length=512)
