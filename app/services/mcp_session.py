"""MCP 客户端会话管理：stdio / SSE / HTTP 懒连接与工具调用。"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from contextlib import AsyncExitStack
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from mcp import ClientSession, StdioServerParameters
from mcp.client.sse import sse_client
from mcp.client.stdio import stdio_client
from mcp.client.streamable_http import streamablehttp_client

from app.core.config import get_settings
from app.core.exceptions import BusinessError, ForbiddenError
from app.core.logger import get_logger
from app.core.security import decrypt_text
from app.db.mysql.models.mcp_server import McpServer, McpTransport

log = get_logger("agent.mcp_session")

_REPO_ROOT = Path(__file__).resolve().parents[2]
_PYTHON_ALIASES = {"python", "python3", "py"}


@dataclass
class DiscoveredTool:
    """MCP 发现的工具。"""

    name: str
    description: str = ""
    input_schema: dict[str, Any] = field(default_factory=dict)


@dataclass
class _LiveSession:
    server_id: int
    server_name: str
    stack: AsyncExitStack
    session: ClientSession
    tools: list[DiscoveredTool] = field(default_factory=list)
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)


class McpSessionManager:
    """进程内 MCP 会话管理器（懒连接）。"""

    def __init__(self) -> None:
        self._sessions: dict[int, _LiveSession] = {}
        self._global_lock = asyncio.Lock()
        self.settings = get_settings()

    def validate_stdio_command(self, command: str) -> None:
        """校验 stdio 命令是否在白名单内。"""
        cmd = (command or "").strip()
        if not cmd:
            raise BusinessError("stdio 命令不能为空")
        # 取 basename（兼容 Windows 路径）
        base = Path(cmd).name.lower()
        # 去掉 .exe
        if base.endswith(".exe"):
            base = base[:-4]
        allow = self.settings.mcp_command_allowlist_set
        if base not in allow:
            raise ForbiddenError(
                f"命令「{base}」不在白名单中，允许: {', '.join(sorted(allow))}"
            )

    def decode_env(self, env_cipher: Optional[str]) -> dict[str, str]:
        """解密环境变量 JSON。"""
        if not env_cipher:
            return {}
        try:
            plain = decrypt_text(env_cipher)
            data = json.loads(plain) if plain else {}
            if not isinstance(data, dict):
                return {}
            return {str(k): str(v) for k, v in data.items()}
        except Exception:
            log.warning("MCP env 解密/解析失败，将使用空环境")
            return {}

    async def discover_tools(self, row: McpServer) -> list[DiscoveredTool]:
        """临时连接并列出工具（用于测试/同步），不保留长连接。"""
        if row.transport == McpTransport.STDIO:
            self.validate_stdio_command(row.command or "")

        stack = AsyncExitStack()
        try:
            session = await self._open_session(stack, row)
            tools = await self._list_tools(session)
            return tools
        finally:
            await stack.aclose()

    async def ensure_session(self, row: McpServer) -> _LiveSession:
        """获取或创建长连接会话。"""
        async with self._global_lock:
            live = self._sessions.get(row.id)
            if live is not None:
                return live
            if row.transport == McpTransport.STDIO:
                self.validate_stdio_command(row.command or "")
            stack = AsyncExitStack()
            try:
                session = await self._open_session(stack, row)
                tools = await self._list_tools(session)
                live = _LiveSession(
                    server_id=row.id,
                    server_name=row.name,
                    stack=stack,
                    session=session,
                    tools=tools,
                )
                self._sessions[row.id] = live
                log.info(f"MCP 会话已建立: id={row.id}, name={row.name}, tools={len(tools)}")
                return live
            except Exception:
                await stack.aclose()
                raise

    async def call_tool(
        self,
        row: McpServer,
        tool_name: str,
        arguments: dict[str, Any],
    ) -> str:
        """调用指定 MCP 工具，返回文本结果。"""
        live = await self.ensure_session(row)
        timeout = max(5, self.settings.mcp_tool_timeout_seconds)
        async with live.lock:
            try:
                result = await asyncio.wait_for(
                    live.session.call_tool(tool_name, arguments or {}),
                    timeout=timeout,
                )
            except asyncio.TimeoutError as e:
                raise BusinessError(f"MCP 工具调用超时（{timeout}s）: {tool_name}") from e
            except Exception as e:
                # 会话可能已死，丢弃后重试一次
                log.warning(f"MCP 调用失败，尝试重建会话: server={row.name}, err={e}")
                await self.close_session(row.id)
                live = await self.ensure_session(row)
                async with live.lock:
                    result = await asyncio.wait_for(
                        live.session.call_tool(tool_name, arguments or {}),
                        timeout=timeout,
                    )

        return self._format_tool_result(result)

    async def close_session(self, server_id: int) -> None:
        """关闭并移除指定会话。"""
        async with self._global_lock:
            live = self._sessions.pop(server_id, None)
        if live is None:
            return
        try:
            await live.stack.aclose()
        except Exception as e:
            log.warning(f"关闭 MCP 会话异常: id={server_id}, err={e}")
        log.info(f"MCP 会话已关闭: id={server_id}")

    async def close_all(self) -> None:
        """关闭全部会话（应用 shutdown）。"""
        async with self._global_lock:
            ids = list(self._sessions.keys())
        for sid in ids:
            await self.close_session(sid)

    async def _open_session(self, stack: AsyncExitStack, row: McpServer) -> ClientSession:
        env = self.decode_env(row.env_cipher)
        if row.transport == McpTransport.STDIO:
            workdir = Path(self.settings.mcp_workdir).resolve()
            workdir.mkdir(parents=True, exist_ok=True)
            merged_env = {**os.environ, **env}
            command, args = self._resolve_stdio_command_args(
                row.command or "",
                list(row.args or []),
            )
            params = StdioServerParameters(
                command=command,
                args=args,
                env=merged_env,
                cwd=str(workdir),
            )
            read, write = await stack.enter_async_context(stdio_client(params))
            session = await stack.enter_async_context(ClientSession(read, write))
            await session.initialize()
            return session

        url = (row.url or "").strip()
        if not url:
            raise BusinessError("sse/http 协议必须配置 URL")
        headers = {k[7:]: v for k, v in env.items() if k.upper().startswith("HEADER_")}
        # 也支持通用 Authorization
        if "AUTHORIZATION" in {k.upper() for k in env}:
            for k, v in env.items():
                if k.upper() == "AUTHORIZATION":
                    headers["Authorization"] = v

        if row.transport == McpTransport.SSE:
            read, write = await stack.enter_async_context(
                sse_client(url, headers=headers or None)
            )
            session = await stack.enter_async_context(ClientSession(read, write))
            await session.initialize()
            return session

        # HTTP → streamable HTTP
        read, write, _get_session_id = await stack.enter_async_context(
            streamablehttp_client(url, headers=headers or None)
        )
        session = await stack.enter_async_context(ClientSession(read, write))
        await session.initialize()
        return session

    async def _list_tools(self, session: ClientSession) -> list[DiscoveredTool]:
        listed = await session.list_tools()
        tools: list[DiscoveredTool] = []
        for t in listed.tools or []:
            schema = t.inputSchema if isinstance(t.inputSchema, dict) else {}
            tools.append(
                DiscoveredTool(
                    name=t.name,
                    description=t.description or "",
                    input_schema=schema,
                )
            )
        return tools

    def _format_tool_result(self, result: Any) -> str:
        """将 MCP CallToolResult 转为字符串。"""
        parts: list[str] = []
        content = getattr(result, "content", None) or []
        for block in content:
            btype = getattr(block, "type", None)
            if btype == "text" or hasattr(block, "text"):
                parts.append(str(getattr(block, "text", "")))
            else:
                try:
                    parts.append(json.dumps(block.model_dump(), ensure_ascii=False))
                except Exception:
                    parts.append(str(block))
        text = "\n".join(p for p in parts if p).strip() or "(empty tool result)"
        if getattr(result, "isError", False):
            text = f"[tool error]\n{text}"
        max_chars = max(500, self.settings.mcp_tool_result_max_chars)
        if len(text) > max_chars:
            text = text[:max_chars] + "…(truncated)"
        return text

    @staticmethod
    def _resolve_stdio_command_args(command: str, args: list[Any]) -> tuple[str, list[str]]:
        """将可移植写法解析为实际可执行路径。

        - command 为 python/python3/py 时，使用当前 API 进程的解释器（同 venv）
        - 相对脚本路径相对仓库根解析（stdio 工作目录是 MCP_WORKDIR，不能靠相对路径）
        """
        cmd = (command or "").strip()
        base = Path(cmd).name.lower()
        if base.endswith(".exe"):
            base = base[:-4]
        if base in _PYTHON_ALIASES:
            cmd = sys.executable

        resolved: list[str] = []
        for raw in args:
            arg = str(raw)
            path = Path(arg)
            if path.is_absolute():
                resolved.append(arg)
                continue
            candidate = (_REPO_ROOT / arg).resolve()
            resolved.append(str(candidate) if candidate.exists() else arg)
        return cmd, resolved


# 全局单例
mcp_session_manager = McpSessionManager()
