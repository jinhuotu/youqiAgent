"""系统信息内部接口。"""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db.mysql.session import get_db
from app.schemas.response.common import ApiResponse
from app.schemas.response.system import SystemInfoResponse
from app.services.system_service import SystemService

router = APIRouter()


@router.get("/info", response_model=ApiResponse[SystemInfoResponse], summary="系统运行状态概览")
def system_info(db: Session = Depends(get_db)) -> ApiResponse[SystemInfoResponse]:
    """返回系统运行状态、模型统计、基础设施连接状态等。"""
    return ApiResponse.ok(SystemService(db).get_info())
