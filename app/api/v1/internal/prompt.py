"""提示词模板内部接口。"""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db.mysql.session import get_db
from app.schemas.request.prompt import PromptCreateRequest, PromptUpdateRequest
from app.schemas.response.common import ApiResponse
from app.schemas.response.prompt import PromptResponse
from app.services.prompt_service import PromptService

router = APIRouter()


@router.get("", response_model=ApiResponse[list[PromptResponse]], summary="获取可用模板列表")
def list_prompts(db: Session = Depends(get_db)) -> ApiResponse[list[PromptResponse]]:
    """获取当前用户可用提示词模板。"""
    return ApiResponse.ok(PromptService(db).list_prompts())


@router.get("/{prompt_id}", response_model=ApiResponse[PromptResponse], summary="获取模板详情")
def get_prompt(prompt_id: int, db: Session = Depends(get_db)) -> ApiResponse[PromptResponse]:
    """获取模板详情。"""
    return ApiResponse.ok(PromptService(db).get_prompt(prompt_id))


@router.post("", response_model=ApiResponse[PromptResponse], summary="新增模板")
def create_prompt(
    req: PromptCreateRequest,
    db: Session = Depends(get_db),
) -> ApiResponse[PromptResponse]:
    """新增提示词模板。"""
    return ApiResponse.ok(PromptService(db).create_prompt(req), message="创建成功")


@router.put("/{prompt_id}", response_model=ApiResponse[PromptResponse], summary="编辑模板")
def update_prompt(
    prompt_id: int,
    req: PromptUpdateRequest,
    db: Session = Depends(get_db),
) -> ApiResponse[PromptResponse]:
    """编辑提示词模板。"""
    return ApiResponse.ok(PromptService(db).update_prompt(prompt_id, req), message="更新成功")


@router.delete("/{prompt_id}", response_model=ApiResponse[None], summary="删除模板")
def delete_prompt(prompt_id: int, db: Session = Depends(get_db)) -> ApiResponse[None]:
    """删除提示词模板。"""
    PromptService(db).delete_prompt(prompt_id)
    return ApiResponse.ok(message="删除成功")
