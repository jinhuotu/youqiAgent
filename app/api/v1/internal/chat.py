"""对话内部接口：非流式 / 流式（SSE）。"""

import json

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.db.mysql.session import get_db
from app.schemas.request.chat import ChatInvokeRequest
from app.schemas.response.chat import ChatInvokeResponse
from app.schemas.response.common import ApiResponse
from app.services.chat_service import ChatService

router = APIRouter()


@router.post(
    "/invoke",
    response_model=ApiResponse[ChatInvokeResponse],
    summary="非流式问答",
)
async def chat_invoke(
    req: ChatInvokeRequest,
    db: Session = Depends(get_db),
) -> ApiResponse[ChatInvokeResponse]:
    """非流式多轮问答，一次性返回完整回答。"""
    result = await ChatService(db).invoke(req)
    return ApiResponse.ok(result)


@router.post("/stream", summary="流式问答（SSE）")
async def chat_stream(
    req: ChatInvokeRequest,
    db: Session = Depends(get_db),
) -> StreamingResponse:
    """基于 SSE 的流式问答。

    事件格式：
    - event: chunk  内容增量
    - event: done   结束元数据
    - event: error  错误信息
    """

    async def event_generator():
        async for item in ChatService(db).stream(req):
            event = item.get("event", "chunk")
            data = json.dumps(item.get("data", {}), ensure_ascii=False)
            yield f"event: {event}\ndata: {data}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
