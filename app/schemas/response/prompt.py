"""提示词模板相关响应 Schema。"""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict

from app.db.mysql.models.model_config import ModelType
from app.db.mysql.models.prompt_template import TemplateScope


class PromptResponse(BaseModel):
    """提示词模板响应。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    content: str
    model_type: Optional[ModelType] = None
    scope: TemplateScope
    user_id: str
    description: Optional[str] = None
    create_time: Optional[datetime] = None
    update_time: Optional[datetime] = None
