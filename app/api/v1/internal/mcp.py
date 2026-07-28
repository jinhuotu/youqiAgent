"""MCP Server 内部接口。"""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db.mysql.session import get_db
from app.schemas.request.mcp import McpServerCreateRequest, McpServerUpdateRequest
from app.schemas.response.common import ApiResponse
from app.schemas.response.mcp import McpServerResponse, McpTestResponse
from app.services.mcp_server_service import McpServerService

router = APIRouter()


@router.get("", response_model=ApiResponse[list[McpServerResponse]], summary="MCP Server 列表")
def list_mcp_servers(db: Session = Depends(get_db)) -> ApiResponse[list[McpServerResponse]]:
    return ApiResponse.ok(McpServerService(db).list_servers())


@router.get(
    "/{server_id}",
    response_model=ApiResponse[McpServerResponse],
    summary="MCP Server 详情",
)
def get_mcp_server(
    server_id: int,
    db: Session = Depends(get_db),
) -> ApiResponse[McpServerResponse]:
    return ApiResponse.ok(McpServerService(db).get_server(server_id))


@router.post("", response_model=ApiResponse[McpServerResponse], summary="新增 MCP Server")
def create_mcp_server(
    req: McpServerCreateRequest,
    db: Session = Depends(get_db),
) -> ApiResponse[McpServerResponse]:
    return ApiResponse.ok(McpServerService(db).create_server(req), message="创建成功")


@router.put(
    "/{server_id}",
    response_model=ApiResponse[McpServerResponse],
    summary="更新 MCP Server",
)
async def update_mcp_server(
    server_id: int,
    req: McpServerUpdateRequest,
    db: Session = Depends(get_db),
) -> ApiResponse[McpServerResponse]:
    return ApiResponse.ok(
        await McpServerService(db).update_server(server_id, req),
        message="更新成功",
    )


@router.delete("/{server_id}", response_model=ApiResponse[None], summary="删除 MCP Server")
async def delete_mcp_server(
    server_id: int,
    db: Session = Depends(get_db),
) -> ApiResponse[None]:
    await McpServerService(db).delete_server(server_id)
    return ApiResponse.ok(message="删除成功")


@router.post(
    "/{server_id}/test",
    response_model=ApiResponse[McpTestResponse],
    summary="测试 MCP 连接",
)
async def test_mcp_server(
    server_id: int,
    db: Session = Depends(get_db),
) -> ApiResponse[McpTestResponse]:
    result = await McpServerService(db).test_connection(server_id)
    return ApiResponse.ok(result, message=result.message)


@router.post(
    "/{server_id}/sync",
    response_model=ApiResponse[McpTestResponse],
    summary="同步 MCP 工具列表",
)
async def sync_mcp_server(
    server_id: int,
    db: Session = Depends(get_db),
) -> ApiResponse[McpTestResponse]:
    result = await McpServerService(db).sync_tools(server_id)
    return ApiResponse.ok(result, message=result.message)
