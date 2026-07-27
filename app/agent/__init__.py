"""预留：LangGraph Agent 与工作流编排扩展位。

后续 MCP 工具、智能体编排、复杂工作流全部基于 LangGraph 构建。
本期仅提供目录骨架与占位说明，不实现具体业务。
"""

from app.core.logger import get_logger

log = get_logger("agent")


class AgentRegistry:
    """智能体注册表（扩展预留）。

    后续可在此注册基于 LangGraph 的 StateGraph / create_agent 实例。
    """

    def __init__(self) -> None:
        self._agents: dict = {}

    def register(self, name: str, agent: object) -> None:
        """注册智能体。"""
        self._agents[name] = agent
        log.info(f"注册 Agent: {name}")

    def get(self, name: str) -> object | None:
        """按名称获取智能体。"""
        return self._agents.get(name)

    def list_names(self) -> list[str]:
        """列出已注册智能体名称。"""
        return list(self._agents.keys())


# 全局注册表单例，供后续 MCP / 工作流模块挂载
agent_registry = AgentRegistry()
