"""知识库文本切分：优先按段落/句子边界，再回退到字符窗口。"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Iterator
from typing import Optional

from app.core.config import get_settings

ChunkCallback = Callable[[int, str], None]

# 从粗到细：段落 → 换行 → 中文句读 → 英文句读 → 逗号/空格 → 硬切
_DEFAULT_SEPARATORS: tuple[str, ...] = (
    "\n\n",
    "\n",
    "。",
    "！",
    "？",
    "；",
    ". ",
    "! ",
    "? ",
    "，",
    ", ",
    " ",
    "",
)


def chunk_text(
    text: str,
    *,
    chunk_size: int | None = None,
    chunk_overlap: int | None = None,
    on_chunk: Optional[ChunkCallback] = None,
) -> list[str]:
    """切分文本为块列表（兼容旧调用方）。"""
    return list(
        iter_chunk_text(
            text,
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            on_chunk=on_chunk,
        )
    )


def iter_chunk_text(
    text: str,
    *,
    chunk_size: int | None = None,
    chunk_overlap: int | None = None,
    on_chunk: Optional[ChunkCallback] = None,
) -> Iterator[str]:
    """流式产出文本块。"""
    settings = get_settings()
    size, overlap = _normalize_size_overlap(chunk_size, chunk_overlap, settings)

    cleaned = (text or "").strip()
    if not cleaned:
        return

    count = 0
    for piece in _split_recursive(cleaned, list(_DEFAULT_SEPARATORS), size, overlap):
        piece = piece.strip()
        if not piece:
            continue
        count += 1
        if on_chunk:
            on_chunk(count, piece)
        yield piece


def iter_chunks_from_parts(
    parts: Iterable[str],
    *,
    chunk_size: int | None = None,
    chunk_overlap: int | None = None,
    joiner: str = "\n\n",
    on_chunk: Optional[ChunkCallback] = None,
) -> Iterator[str]:
    """按片段增量切分（如 PDF 逐页），缓冲过大时提前产出完整块。"""
    settings = get_settings()
    size, overlap = _normalize_size_overlap(chunk_size, chunk_overlap, settings)
    flush_at = max(size * 2, size + 1)

    buffer = ""
    count = 0

    def emit(chunk: str) -> str | None:
        nonlocal count
        chunk = chunk.strip()
        if not chunk:
            return None
        count += 1
        if on_chunk:
            on_chunk(count, chunk)
        return chunk

    for part in parts:
        piece = (part or "").strip()
        if not piece:
            continue
        buffer = f"{buffer}{joiner}{piece}" if buffer else piece

        while len(buffer) >= flush_at:
            window = buffer[:flush_at]
            rest = buffer[flush_at:]
            splits = [
                c.strip()
                for c in _split_recursive(
                    window, list(_DEFAULT_SEPARATORS), size, overlap
                )
                if c.strip()
            ]
            if len(splits) <= 1:
                hard = buffer[:size]
                buffer = buffer[size - overlap :] if overlap else buffer[size:]
                out = emit(hard)
                if out:
                    yield out
                continue
            *ready, tail = splits
            for c in ready:
                out = emit(c)
                if out:
                    yield out
            buffer = f"{tail}{joiner}{rest}" if rest else tail

    if buffer.strip():
        for chunk in _split_recursive(
            buffer.strip(), list(_DEFAULT_SEPARATORS), size, overlap
        ):
            out = emit(chunk)
            if out:
                yield out


def _normalize_size_overlap(
    chunk_size: int | None,
    chunk_overlap: int | None,
    settings,
) -> tuple[int, int]:
    size = chunk_size or settings.kb_chunk_size
    overlap = chunk_overlap or settings.kb_chunk_overlap
    if size <= 0:
        size = 800
    if overlap < 0 or overlap >= size:
        overlap = max(0, size // 8)
    return size, overlap


def _split_recursive(
    text: str,
    separators: list[str],
    chunk_size: int,
    chunk_overlap: int,
) -> list[str]:
    """递归按分隔符切分，尽量在语义边界断开。"""
    if not text:
        return []
    if len(text) <= chunk_size:
        return [text]

    separator = separators[-1] if separators else ""
    next_seps: list[str] = []
    for i, sep in enumerate(separators):
        if sep == "":
            separator = ""
            break
        if sep in text:
            separator = sep
            next_seps = separators[i + 1 :]
            break

    if separator == "":
        return _split_by_chars(text, chunk_size, chunk_overlap)

    splits = text.split(separator)
    pieces: list[str] = []
    for i, part in enumerate(splits):
        if i < len(splits) - 1:
            pieces.append(part + separator)
        elif part:
            pieces.append(part)

    merged = _merge_splits(pieces, chunk_size, chunk_overlap)
    final: list[str] = []
    for m in merged:
        if len(m) <= chunk_size:
            final.append(m)
        else:
            final.extend(
                _split_recursive(m, next_seps or [""], chunk_size, chunk_overlap)
            )
    return final


def _merge_splits(splits: list[str], chunk_size: int, chunk_overlap: int) -> list[str]:
    """将小片段合并到接近 chunk_size，并保留 overlap。"""
    if not splits:
        return []
    chunks: list[str] = []
    current = ""
    for part in splits:
        if not part:
            continue
        candidate = current + part if current else part
        if len(candidate) <= chunk_size:
            current = candidate
            continue
        if current:
            chunks.append(current)
            if chunk_overlap > 0:
                tail = current[-chunk_overlap:]
                current = tail + part
                if len(current) > chunk_size:
                    current = part
            else:
                current = part
        else:
            chunks.append(part)
            current = ""
    if current:
        chunks.append(current)
    return chunks


def _split_by_chars(text: str, chunk_size: int, chunk_overlap: int) -> list[str]:
    """最终硬切：定长窗口 + 重叠。"""
    chunks: list[str] = []
    start = 0
    length = len(text)
    while start < length:
        end = min(start + chunk_size, length)
        piece = text[start:end]
        if piece:
            chunks.append(piece)
        if end >= length:
            break
        start = max(0, end - chunk_overlap)
    return chunks
