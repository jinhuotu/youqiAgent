"""模型管理内部接口。"""

from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.db.mysql.models.model_config import ModelType
from app.db.mysql.session import get_db
from app.schemas.request.model import ModelCreateRequest, ModelUpdateRequest
from app.schemas.response.common import ApiResponse
from app.schemas.response.model import ModelResponse
from app.services.model_service import ModelService

router = APIRouter()


@router.get("", response_model=ApiResponse[list[ModelResponse]], summary="获取可用模型列表")
def list_models(
    type: Optional[ModelType] = Query(default=None, description="按模态类型筛选"),
    status: Optional[int] = Query(default=None, description="按状态筛选 1/0"),
    db: Session = Depends(get_db),
) -> ApiResponse[list[ModelResponse]]:
    """获取当前用户可用模型列表（公共 + 私有）。"""
    service = ModelService(db)
    data = service.list_models(model_type=type, status=status)
    return ApiResponse.ok(data)


@router.get("/{model_id}", response_model=ApiResponse[ModelResponse], summary="获取模型详情")
def get_model(model_id: int, db: Session = Depends(get_db)) -> ApiResponse[ModelResponse]:
    """获取单个模型详情。"""
    service = ModelService(db)
    return ApiResponse.ok(service.get_model(model_id))


@router.post("", response_model=ApiResponse[ModelResponse], summary="新增模型配置")
def create_model(
    req: ModelCreateRequest,
    db: Session = Depends(get_db),
) -> ApiResponse[ModelResponse]:
    """新增模型配置。"""
    service = ModelService(db)
    return ApiResponse.ok(service.create_model(req), message="创建成功")


@router.put("/{model_id}", response_model=ApiResponse[ModelResponse], summary="修改模型配置")
def update_model(
    model_id: int,
    req: ModelUpdateRequest,
    db: Session = Depends(get_db),
) -> ApiResponse[ModelResponse]:
    """修改模型配置。"""
    service = ModelService(db)
    return ApiResponse.ok(service.update_model(model_id, req), message="更新成功")


@router.delete("/{model_id}", response_model=ApiResponse[None], summary="删除模型配置")
def delete_model(model_id: int, db: Session = Depends(get_db)) -> ApiResponse[None]:
    """删除模型配置。"""
    service = ModelService(db)
    service.delete_model(model_id)
    return ApiResponse.ok(message="删除成功")
