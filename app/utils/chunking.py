"""文本切分工具（知识库最小闭环）。"""

from collections.abc import Callable
from typing import Optional

from app.core.config import get_settings

ChunkCallback = Callable[[int, str], None]


def chunk_text(
    text: str,
    *,
    chunk_size: int | None = None,
    chunk_overlap: int | None = None,
    on_chunk: Optional[ChunkCallback] = None,
) -> list[str]:
    """按字符长度切分文本，保留重叠窗口。

    Args:
        text: 原文
        chunk_size: 块大小
        chunk_overlap: 重叠长度
        on_chunk: 每产出一块回调 (当前已切块数, 块内容)，用于实时进度

    Returns:
        非空文本块列表
    """
    settings = get_settings()
    size = chunk_size or settings.kb_chunk_size
    overlap = chunk_overlap or settings.kb_chunk_overlap
    if size <= 0:
        size = 800
    if overlap < 0 or overlap >= size:
        overlap = max(0, size // 8)

    cleaned = (text or "").strip()
    if not cleaned:
        return []
    if len(cleaned) <= size:
        chunks = [cleaned]
        if on_chunk:
            on_chunk(1, cleaned)
        return chunks

    chunks: list[str] = []
    start = 0
    length = len(cleaned)
    while start < length:
        end = min(start + size, length)
        piece = cleaned[start:end].strip()
        if piece:
            chunks.append(piece)
            if on_chunk:
                on_chunk(len(chunks), piece)
        if end >= length:
            break
        start = end - overlap
    return chunks
