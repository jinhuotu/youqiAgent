"""Agent / MCP 扩展入口。

提供全局 AgentRegistry，并暴露 MCP 会话管理器供业务层使用。
"""

from app.core.logger import get_logger
from app.services.mcp_session import mcp_session_manager

log = get_logger("agent")


class AgentRegistry:
    """智能体/工具集注册表。"""

    def __init__(self) -> None:
        self._agents: dict = {}

    def register(self, name: str, agent: object) -> None:
        self._agents[name] = agent
        log.info(f"注册 Agent: {name}")

    def get(self, name: str) -> object | None:
        return self._agents.get(name)

    def list_names(self) -> list[str]:
        return list(self._agents.keys())


agent_registry = AgentRegistry()

__all__ = ["agent_registry", "mcp_session_manager", "AgentRegistry"]
