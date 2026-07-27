"""统一 LLM 基类与工厂。

基于 LangChain ChatModel 标准接口，确保不同厂商调用方式完全统一。
"""

from abc import ABC, abstractmethod
from typing import Any, AsyncIterator, Optional

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage

from app.core.exceptions import BusinessError
from app.core.logger import get_logger
from app.core.security import decrypt_text

log = get_logger("services.llm")


def to_lc_messages(messages: list[dict[str, str]]) -> list[BaseMessage]:
    """将标准角色字典转为 LangChain Message 对象。

    Args:
        messages: [{"role": "system|user|assistant", "content": "..."}]
    """
    result: list[BaseMessage] = []
    for msg in messages:
        role = msg.get("role", "user")
        content = msg.get("content", "")
        if role == "system":
            result.append(SystemMessage(content=content))
        elif role == "assistant":
            result.append(AIMessage(content=content))
        else:
            result.append(HumanMessage(content=content))
    return result


class BaseLLMProvider(ABC):
    """LLM 提供商抽象基类。

    子类负责根据配置构建 LangChain ChatModel 实例。
    """

    @abstractmethod
    def build_chat_model(
        self,
        *,
        base_url: str,
        api_key: str,
        model_id: str,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
    ) -> BaseChatModel:
        """构建 ChatModel 实例。"""


class LLMFactory:
    """LLM 工厂：按 provider 选择实现并创建 ChatModel。"""

    _providers: dict[str, BaseLLMProvider] = {}

    @classmethod
    def register(cls, name: str, provider: BaseLLMProvider) -> None:
        """注册提供商实现。"""
        cls._providers[name] = provider

    @classmethod
    def create(
        cls,
        *,
        provider: str,
        base_url: str,
        api_key: str,
        model_id: str,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
    ) -> BaseChatModel:
        """创建 ChatModel。

        Args:
            provider: 提供商标识
            base_url: 接口地址
            api_key: API 密钥（已解密明文）
            model_id: 模型标识
            temperature: 温度
            max_tokens: 最大生成 token

        Raises:
            BusinessError: 未知 provider
        """
        # 归一化：deepseek / zhipu / openai 等均走 openai_compatible
        key = provider.lower().strip()
        if key in ("deepseek", "zhipu", "openai", "autodl", "openai_compatible"):
            key = "openai_compatible"
        if key not in cls._providers:
            raise BusinessError(f"不支持的模型提供商: {provider}")
        return cls._providers[key].build_chat_model(
            base_url=base_url,
            api_key=api_key,
            model_id=model_id,
            temperature=temperature,
            max_tokens=max_tokens,
        )

    @classmethod
    def create_from_model_row(
        cls,
        model_row: Any,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
    ) -> BaseChatModel:
        """从 ORM 模型配置行创建 ChatModel（自动解密 api_key）。"""
        plain_key = decrypt_text(model_row.api_key or "")
        return cls.create(
            provider=model_row.provider,
            base_url=model_row.base_url,
            api_key=plain_key,
            model_id=model_row.model_id,
            temperature=temperature,
            max_tokens=max_tokens,
        )


async def ainvoke_chat(
    chat_model: BaseChatModel,
    messages: list[dict[str, str]],
) -> str:
    """非流式调用：返回完整助手回复文本。

    Args:
        chat_model: LangChain ChatModel
        messages: 标准消息列表

    Returns:
        助手回复文本
    """
    lc_messages = to_lc_messages(messages)
    log.info(f"LLM 非流式调用开始，消息数={len(lc_messages)}")
    response = await chat_model.ainvoke(lc_messages)
    content = response.content if hasattr(response, "content") else str(response)
    if isinstance(content, list):
        # 多模态内容块兼容
        content = "".join(
            block.get("text", "") if isinstance(block, dict) else str(block)
            for block in content
        )
    log.info("LLM 非流式调用完成")
    return str(content)


async def astream_chat(
    chat_model: BaseChatModel,
    messages: list[dict[str, str]],
) -> AsyncIterator[str]:
    """流式调用：逐块产出增量文本。

    Args:
        chat_model: LangChain ChatModel
        messages: 标准消息列表

    Yields:
        增量文本片段
    """
    lc_messages = to_lc_messages(messages)
    log.info(f"LLM 流式调用开始，消息数={len(lc_messages)}")
    async for chunk in chat_model.astream(lc_messages):
        content = chunk.content if hasattr(chunk, "content") else ""
        if isinstance(content, list):
            content = "".join(
                block.get("text", "") if isinstance(block, dict) else str(block)
                for block in content
            )
        if content:
            yield str(content)
    log.info("LLM 流式调用完成")
