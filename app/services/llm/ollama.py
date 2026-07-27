"""Ollama 本地部署模型实现。"""

from typing import Optional

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_ollama import ChatOllama

from app.core.logger import get_logger
from app.services.llm.base import BaseLLMProvider, LLMFactory

log = get_logger("services.llm.ollama")


class OllamaProvider(BaseLLMProvider):
    """基于 langchain-ollama ChatOllama 的本地模型实现。"""

    def build_chat_model(
        self,
        *,
        base_url: str,
        api_key: str,
        model_id: str,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
    ) -> BaseChatModel:
        """构建 ChatOllama 实例。

        注意：Ollama 通常不需要 api_key，base_url 指向本地服务。
        """
        kwargs: dict = {
            "model": model_id,
            "base_url": base_url.rstrip("/") if base_url else "http://127.0.0.1:11434",
            "temperature": temperature,
        }
        if max_tokens is not None:
            kwargs["num_predict"] = max_tokens
        log.info(f"创建 Ollama ChatModel: model={model_id}, base_url={base_url}")
        return ChatOllama(**kwargs)


LLMFactory.register("ollama", OllamaProvider())
