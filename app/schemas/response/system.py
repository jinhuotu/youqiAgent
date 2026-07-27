"""系统信息响应 Schema。"""

from pydantic import BaseModel, Field


class SystemInfoResponse(BaseModel):
    """系统运行状态概览。"""

    version: str = Field(..., description="系统版本号")
    env: str = Field(..., description="运行环境")
    enabled_model_total: int = Field(default=0, description="已启用模型总数")
    model_type_counts: dict[str, int] = Field(
        default_factory=dict,
        description="各模态类型数量",
    )
    user_conversation_total: int = Field(default=0, description="当前用户会话总数")
    mysql_status: bool = Field(default=False, description="MySQL 连接状态")
    redis_status: bool = Field(default=False, description="Redis 连接状态")
    chroma_status: bool = Field(default=False, description="Chroma 连接状态")
