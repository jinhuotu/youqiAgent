"""OpenAI 协议兼容模型实现。

适用于 DeepSeek、智谱 AI、AutoDL 部署模型等所有 OpenAI Compatible 接口。
"""

from typing import Optional

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_openai import ChatOpenAI

from app.core.logger import get_logger
from app.services.llm.base import BaseLLMProvider, LLMFactory

log = get_logger("services.llm.openai_compatible")


class OpenAICompatibleProvider(BaseLLMProvider):
    """基于 langchain-openai ChatOpenAI 的兼容实现。"""

    def build_chat_model(
        self,
        *,
        base_url: str,
        api_key: str,
        model_id: str,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
    ) -> BaseChatModel:
        """构建 ChatOpenAI 实例。"""
        kwargs: dict = {
            "model": model_id,
            "api_key": api_key or "EMPTY",
            "base_url": base_url.rstrip("/") if base_url else None,
            "temperature": temperature,
            "streaming": True,
        }
        if max_tokens is not None:
            kwargs["max_tokens"] = max_tokens
        log.info(f"创建 OpenAI 兼容 ChatModel: model={model_id}, base_url={base_url}")
        return ChatOpenAI(**kwargs)


# 模块加载时自动注册
LLMFactory.register("openai_compatible", OpenAICompatibleProvider())
