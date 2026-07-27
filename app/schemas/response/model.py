"""模型管理相关响应 Schema。"""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from app.db.mysql.models.model_config import ModelScope, ModelType


class ModelResponse(BaseModel):
    """模型配置响应（API Key 已脱敏）。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    type: ModelType
    provider: str
    base_url: str
    api_key_masked: str = Field(default="", description="脱敏后的 API Key")
    model_id: str
    max_context: int
    scope: ModelScope
    user_id: str
    status: int
    create_time: Optional[datetime] = None
    update_time: Optional[datetime] = None
