"""Embedding 模型构建工具。"""

from typing import Any

from langchain_openai import OpenAIEmbeddings
from openai import APIStatusError, NotFoundError

from app.core.exceptions import BusinessError
from app.core.logger import get_logger
from app.core.security import decrypt_text
from app.services.llm.http import build_async_http_client, build_sync_http_client

log = get_logger("services.llm.embedding")


def build_embeddings_from_model_row(model_row: Any) -> OpenAIEmbeddings:
    """从模型配置行构建 OpenAI 兼容 Embedding 客户端。

    适用于 openai_compatible / deepseek / ollama（若提供 /embeddings）等。
    """
    provider = (model_row.provider or "").lower().strip()
    if provider not in (
        "openai_compatible",
        "deepseek",
        "zhipu",
        "openai",
        "autodl",
        "ollama",
        "",
    ):
        raise BusinessError(f"当前不支持该提供商作为 Embedding: {model_row.provider}")

    plain_key = decrypt_text(model_row.api_key or "")
    base_url = (model_row.base_url or "").rstrip("/") or None
    log.info(
        f"创建 Embedding 客户端: model={model_row.model_id}, base_url={base_url}"
    )
    # check_embedding_ctx_length=False：直接传字符串，避免默认把文本编成 token id。
    # OpenAI 官方可接受 token 数组，但阿里云百炼/MAAS 等兼容接口只接受 str / list[str]，
    # 否则会报：contents is neither str nor list of str.: input.contents
    return OpenAIEmbeddings(
        model=model_row.model_id,
        api_key=plain_key or "EMPTY",
        base_url=base_url,
        check_embedding_ctx_length=False,
        http_client=build_sync_http_client(connect=8.0, read=20.0),
        http_async_client=build_async_http_client(connect=8.0, read=20.0),
    )


def _format_embedding_api_error(model_row: Any, exc: Exception) -> str:
    """将上游 Embedding 接口错误转为可读业务提示。"""
    model_id = getattr(model_row, "model_id", "?")
    base_url = (getattr(model_row, "base_url", None) or "").rstrip("/") or "(默认)"
    status = getattr(exc, "status_code", None)
    detail = ""
    body = getattr(exc, "body", None)
    if isinstance(body, dict):
        err = body.get("error") or body
        if isinstance(err, dict):
            detail = str(err.get("message") or err.get("msg") or "")[:200]
        else:
            detail = str(err)[:200]
    elif body is not None:
        detail = str(body)[:200]
    if not detail:
        detail = str(exc)[:200]

    if status == 404 or isinstance(exc, NotFoundError):
        return (
            f"Embedding 接口返回 404：模型「{model_id}」在 {base_url} 上不可用。"
            f"请确认：1) 知识库绑定的是支持 /v1/embeddings 的向量模型（不要用纯对话模型）；"
            f"2) base_url 指向正确的 OpenAI 兼容地址（通常以 /v1 结尾）；"
            f"3) model_id 与服务端已部署名称一致。"
            f" 上游信息: {detail}"
        )
    return (
        f"Embedding 调用失败（model={model_id}, base_url={base_url}"
        f"{f', http={status}' if status else ''}）: {detail}"
    )


def embed_query(model_row: Any, text: str) -> list[float]:
    """对查询文本做 Embedding，上游错误转为 BusinessError。"""
    embedder = build_embeddings_from_model_row(model_row)
    try:
        return embedder.embed_query(text)
    except (NotFoundError, APIStatusError) as e:
        raise BusinessError(_format_embedding_api_error(model_row, e)) from e
    except Exception as e:
        raise BusinessError(_format_embedding_api_error(model_row, e)) from e


def embed_documents(model_row: Any, texts: list[str]) -> list[list[float]]:
    """对文档块做 Embedding，上游错误转为 BusinessError。"""
    embedder = build_embeddings_from_model_row(model_row)
    try:
        return embedder.embed_documents(texts)
    except (NotFoundError, APIStatusError) as e:
        raise BusinessError(_format_embedding_api_error(model_row, e)) from e
    except Exception as e:
        raise BusinessError(_format_embedding_api_error(model_row, e)) from e
