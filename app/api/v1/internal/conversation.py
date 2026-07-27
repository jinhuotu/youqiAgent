"""会话管理内部接口。"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.db.mysql.session import get_db
from app.schemas.request.chat import ConversationCreateRequest, ConversationUpdateRequest
from app.schemas.response.chat import ConversationResponse
from app.schemas.response.common import ApiResponse, PageResult
from app.services.chat_service import ChatService
from app.services.conversation_service import ConversationService

router = APIRouter()


@router.get(
    "",
    response_model=ApiResponse[PageResult[ConversationResponse]],
    summary="获取会话列表",
)
def list_conversations(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
) -> ApiResponse[PageResult[ConversationResponse]]:
    """分页获取当前用户会话列表。"""
    data = ConversationService(db).list_conversations(page=page, page_size=page_size)
    return ApiResponse.ok(data)


@router.get(
    "/{conversation_id}",
    response_model=ApiResponse[ConversationResponse],
    summary="获取会话详情+历史消息",
)
def get_conversation(
    conversation_id: int,
    msg_page: int = Query(default=1, ge=1),
    msg_page_size: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
) -> ApiResponse[ConversationResponse]:
    """获取会话详情及历史消息。"""
    data = ConversationService(db).get_conversation(
        conversation_id,
        with_messages=True,
        msg_page=msg_page,
        msg_page_size=msg_page_size,
    )
    return ApiResponse.ok(data)


@router.post("", response_model=ApiResponse[ConversationResponse], summary="新建会话")
def create_conversation(
    req: ConversationCreateRequest,
    db: Session = Depends(get_db),
) -> ApiResponse[ConversationResponse]:
    """新建会话。"""
    return ApiResponse.ok(ConversationService(db).create(req), message="创建成功")


@router.put(
    "/{conversation_id}",
    response_model=ApiResponse[ConversationResponse],
    summary="修改会话标题",
)
def update_conversation(
    conversation_id: int,
    req: ConversationUpdateRequest,
    db: Session = Depends(get_db),
) -> ApiResponse[ConversationResponse]:
    """修改会话标题。"""
    return ApiResponse.ok(
        ConversationService(db).update_title(conversation_id, req),
        message="更新成功",
    )


@router.delete(
    "/{conversation_id}",
    response_model=ApiResponse[None],
    summary="删除会话",
)
def delete_conversation(
    conversation_id: int,
    db: Session = Depends(get_db),
) -> ApiResponse[None]:
    """删除会话及全部消息。"""
    ConversationService(db).delete(conversation_id)
    return ApiResponse.ok(message="删除成功")


@router.post(
    "/{conversation_id}/summary",
    response_model=ApiResponse[ConversationResponse],
    summary="主动触发会话总结",
)
async def summarize_conversation(
    conversation_id: int,
    db: Session = Depends(get_db),
) -> ApiResponse[ConversationResponse]:
    """主动触发会话历史总结。"""
    conversation = await ChatService(db).trigger_summary(conversation_id)
    data = ConversationService(db).get_conversation(conversation.id, with_messages=False)
    return ApiResponse.ok(data, message="总结完成")
