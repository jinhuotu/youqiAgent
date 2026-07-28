"""MCP Server 业务服务：CRUD / 测试 / 同步工具列表。"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.context import get_current_role, get_current_user_id
from app.core.exceptions import BusinessError, ForbiddenError, NotFoundError
from app.core.logger import get_logger
from app.core.security import encrypt_text
from app.db.mysql.models.mcp_server import McpScope, McpServer, McpTransport
from app.schemas.request.mcp import McpServerCreateRequest, McpServerUpdateRequest
from app.schemas.response.mcp import McpServerResponse, McpTestResponse, McpToolInfo
from app.services.mcp_session import mcp_session_manager
from app.services.mcp_tool_adapter import (
    cache_to_discovered,
    tools_to_cache,
)

log = get_logger("services.mcp")


class McpServerService:
    """MCP Server 管理。仅管理员可维护。"""

    def __init__(self, db: Session) -> None:
        self.db = db
        self.settings = get_settings()

    def _assert_admin(self) -> None:
        if not self.settings.enable_admin_role or get_current_role() != "admin":
            raise ForbiddenError("仅管理员可管理 MCP Server")

    def _to_response(self, row: McpServer) -> McpServerResponse:
        cache = row.tool_cache if isinstance(row.tool_cache, list) else []
        tools = [
            McpToolInfo(
                name=str(i.get("name") or ""),
                description=str(i.get("description") or ""),
                input_schema=i.get("input_schema")
                if isinstance(i.get("input_schema"), dict)
                else {},
            )
            for i in cache
            if isinstance(i, dict) and i.get("name")
        ]
        is_admin = self.settings.enable_admin_role and get_current_role() == "admin"
        env: Optional[dict[str, str]] = None
        if is_admin and row.env_cipher:
            decoded = mcp_session_manager.decode_env(row.env_cipher)
            env = decoded or None
        return McpServerResponse(
            id=row.id,
            name=row.name,
            description=row.description,
            transport=row.transport,
            command=row.command,
            args=row.args if isinstance(row.args, list) else None,
            url=row.url,
            has_env=bool(row.env_cipher),
            env=env,
            scope=row.scope,
            status=row.status,
            tool_cache=tools,
            tool_count=len(tools),
            last_sync_at=row.last_sync_at,
            last_error=row.last_error,
            user_id=row.user_id,
            create_time=row.create_time,
            update_time=row.update_time,
        )

    def list_servers(self) -> list[McpServerResponse]:
        """列表：管理员看全部；普通用户只看启用的公共配置（只读）。"""
        role = get_current_role()
        if self.settings.enable_admin_role and role == "admin":
            rows = self.db.scalars(select(McpServer).order_by(McpServer.id.desc())).all()
        else:
            rows = self.db.scalars(
                select(McpServer)
                .where(
                    McpServer.status == 1,
                    McpServer.scope == McpScope.PUBLIC,
                )
                .order_by(McpServer.id.desc())
            ).all()
        return [self._to_response(r) for r in rows]

    def get_server(self, server_id: int) -> McpServerResponse:
        row = self.db.get(McpServer, server_id)
        if row is None:
            raise NotFoundError("MCP Server 不存在")
        role = get_current_role()
        if not (self.settings.enable_admin_role and role == "admin"):
            if row.status != 1 or row.scope != McpScope.PUBLIC:
                raise ForbiddenError("无权查看该 MCP Server")
        return self._to_response(row)

    def create_server(self, req: McpServerCreateRequest) -> McpServerResponse:
        self._assert_admin()
        exists = self.db.scalar(select(McpServer.id).where(McpServer.name == req.name))
        if exists:
            raise BusinessError(f"名称已存在: {req.name}")
        if req.transport == McpTransport.STDIO:
            mcp_session_manager.validate_stdio_command(req.command or "")

        env_cipher = None
        if req.env:
            env_cipher = encrypt_text(json.dumps(req.env, ensure_ascii=False))

        row = McpServer(
            name=req.name.strip(),
            description=req.description,
            transport=req.transport,
            command=(req.command or "").strip() or None,
            args=list(req.args or []),
            url=(req.url or "").strip() or None,
            env_cipher=env_cipher,
            scope=req.scope,
            user_id="0" if req.scope == McpScope.PUBLIC else get_current_user_id(),
            status=req.status,
            tool_cache=[],
        )
        self.db.add(row)
        self.db.commit()
        self.db.refresh(row)
        log.info(f"创建 MCP Server: id={row.id}, name={row.name}")
        return self._to_response(row)

    async def update_server(
        self,
        server_id: int,
        req: McpServerUpdateRequest,
    ) -> McpServerResponse:
        self._assert_admin()
        row = self.db.get(McpServer, server_id)
        if row is None:
            raise NotFoundError("MCP Server 不存在")

        data = req.model_dump(exclude_unset=True)
        if "name" in data and data["name"] != row.name:
            exists = self.db.scalar(
                select(McpServer.id).where(
                    McpServer.name == data["name"],
                    McpServer.id != server_id,
                )
            )
            if exists:
                raise BusinessError(f"名称已存在: {data['name']}")

        if "env" in data:
            env = data.pop("env")
            if env is None:
                row.env_cipher = None
            else:
                row.env_cipher = encrypt_text(json.dumps(env, ensure_ascii=False))

        transport = data.get("transport", row.transport)
        command = data.get("command", row.command)
        if transport == McpTransport.STDIO or (
            "command" in data and row.transport == McpTransport.STDIO
        ):
            if (transport == McpTransport.STDIO) or row.transport == McpTransport.STDIO:
                cmd = command if command is not None else row.command
                if cmd:
                    mcp_session_manager.validate_stdio_command(cmd)

        for key, value in data.items():
            if key == "args" and value is not None:
                setattr(row, key, list(value))
            elif hasattr(row, key):
                setattr(row, key, value)

        if row.scope == McpScope.PUBLIC:
            row.user_id = "0"

        self.db.commit()
        self.db.refresh(row)
        await mcp_session_manager.close_session(row.id)
        log.info(f"更新 MCP Server: id={row.id}")
        return self._to_response(row)

    async def delete_server(self, server_id: int) -> None:
        self._assert_admin()
        row = self.db.get(McpServer, server_id)
        if row is None:
            raise NotFoundError("MCP Server 不存在")
        self.db.delete(row)
        self.db.commit()
        await mcp_session_manager.close_session(server_id)
        log.info(f"删除 MCP Server: id={server_id}")

    async def test_connection(self, server_id: int) -> McpTestResponse:
        """测试连接并返回工具列表（不强制写缓存）。"""
        self._assert_admin()
        row = self.db.get(McpServer, server_id)
        if row is None:
            raise NotFoundError("MCP Server 不存在")
        try:
            tools = await mcp_session_manager.discover_tools(row)
            infos = [
                McpToolInfo(
                    name=t.name,
                    description=t.description,
                    input_schema=t.input_schema,
                )
                for t in tools
            ]
            row.last_error = None
            self.db.commit()
            return McpTestResponse(
                ok=True,
                message=f"连通成功，发现 {len(infos)} 个工具",
                tools=infos,
            )
        except Exception as e:
            msg = self._format_connect_error(row, e)
            row.last_error = msg
            self.db.commit()
            return McpTestResponse(ok=False, message=msg, tools=[])

    async def sync_tools(self, server_id: int) -> McpTestResponse:
        """测试连接并将工具列表写入缓存。"""
        self._assert_admin()
        row = self.db.get(McpServer, server_id)
        if row is None:
            raise NotFoundError("MCP Server 不存在")
        try:
            tools = await mcp_session_manager.discover_tools(row)
            row.tool_cache = tools_to_cache(tools)
            row.last_sync_at = datetime.now()
            row.last_error = None
            self.db.commit()
            self.db.refresh(row)
            infos = [
                McpToolInfo(
                    name=t.name,
                    description=t.description,
                    input_schema=t.input_schema,
                )
                for t in tools
            ]
            # 刷新长连接缓存
            await mcp_session_manager.close_session(server_id)
            return McpTestResponse(
                ok=True,
                message=f"同步成功，共 {len(infos)} 个工具",
                tools=infos,
            )
        except Exception as e:
            msg = self._format_connect_error(row, e)
            row.last_error = msg
            self.db.commit()
            return McpTestResponse(ok=False, message=msg, tools=[])

    @staticmethod
    def _format_connect_error(row: McpServer, exc: Exception) -> str:
        """生成可读的连接失败信息（含启动命令，便于排查包名错误）。"""
        base = str(exc).strip() or exc.__class__.__name__
        if row.transport == McpTransport.STDIO:
            parts = [row.command or ""] + [str(a) for a in (row.args or [])]
            cmdline = " ".join(p for p in parts if p).strip()
            hint = ""
            joined = " ".join(str(a) for a in (row.args or [])).lower()
            if "@azure/mssql-mcp" in joined:
                hint = (
                    "；提示: npm 上不存在 @azure/mssql-mcp，"
                    "请将参数改为每行: -y 与 mssql-mcp-server"
                )
            elif "connection closed" in base.lower():
                hint = "；常见原因: 包名不存在、npx 拉包失败、或子进程启动后立即退出"
            msg = f"{base}（启动: {cmdline or '(空)'}）{hint}"
        else:
            msg = f"{base}（url: {(row.url or '').strip() or '(空)'}）"
        return msg[:800]

    def list_enabled_for_chat(
        self,
        *,
        mcp_server_ids: Optional[list[int]] = None,
    ) -> list[McpServer]:
        """对话可用的启用 MCP Server（全局）。"""
        stmt = select(McpServer).where(McpServer.status == 1)
        if mcp_server_ids:
            stmt = stmt.where(McpServer.id.in_(mcp_server_ids))
        return list(self.db.scalars(stmt.order_by(McpServer.id.asc())).all())

    def build_tool_bundles(
        self,
        *,
        mcp_server_ids: Optional[list[int]] = None,
    ) -> list[tuple[McpServer, list]]:
        """启用 server + 缓存工具（若无缓存则空列表，调用方应先 sync）。"""
        rows = self.list_enabled_for_chat(mcp_server_ids=mcp_server_ids)
        bundles = []
        for row in rows:
            tools = cache_to_discovered(row.tool_cache)
            if tools:
                bundles.append((row, tools))
        return bundles
