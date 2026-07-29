"""知识库检索后处理：距离门槛与邻块扩展。"""

from __future__ import annotations

from typing import Any, Optional


def parse_chunk_id(chunk_id: str) -> tuple[str, Optional[int]]:
    """解析 doc_{id}_chunk_{i} → (prefix, index)。"""
    marker = "_chunk_"
    if marker not in chunk_id:
        return chunk_id, None
    prefix, idx_s = chunk_id.rsplit(marker, 1)
    try:
        return prefix, int(idx_s)
    except ValueError:
        return chunk_id, None


def neighbor_chunk_ids(chunk_id: str, window: int) -> list[str]:
    """生成邻块 ID，按阅读顺序：左…右。"""
    if window <= 0:
        return []
    prefix, idx = parse_chunk_id(chunk_id)
    if idx is None:
        return []
    out: list[str] = []
    for nidx in range(idx - window, idx):
        if nidx >= 0:
            out.append(f"{prefix}_chunk_{nidx}")
    for nidx in range(idx + 1, idx + window + 1):
        out.append(f"{prefix}_chunk_{nidx}")
    return out


def filter_by_max_distance(
    hits: list[dict[str, Any]],
    max_distance: float,
) -> list[dict[str, Any]]:
    """保留 distance <= max_distance 的命中；max_distance<=0 表示不过滤。"""
    if max_distance <= 0:
        return list(hits)
    kept: list[dict[str, Any]] = []
    for hit in hits:
        dist = hit.get("distance")
        if dist is None:
            kept.append(hit)
            continue
        try:
            if float(dist) <= max_distance:
                kept.append(hit)
        except (TypeError, ValueError):
            kept.append(hit)
    return kept


def expand_hits_with_neighbors(
    primary_hits: list[dict[str, Any]],
    fetched_by_id: dict[str, dict[str, Any]],
    *,
    window: int,
    max_total: int,
) -> list[dict[str, Any]]:
    """主命中优先，再插入邻块，去重并限制总条数。"""
    ordered: list[dict[str, Any]] = []
    seen: set[str] = set()

    def _add(hit: dict[str, Any]) -> bool:
        hid = str(hit.get("id") or "")
        if not hid or hid in seen or len(ordered) >= max_total:
            return False
        seen.add(hid)
        ordered.append(hit)
        return True

    for hit in primary_hits:
        if len(ordered) >= max_total:
            break
        _add(hit)
        for nid in neighbor_chunk_ids(str(hit.get("id") or ""), window):
            doc = fetched_by_id.get(nid)
            if doc:
                _add(doc)
            if len(ordered) >= max_total:
                break
    return ordered


def score_eval_hit(
    hits: list[dict[str, Any]],
    *,
    expect_contains: Optional[str] = None,
    expect_doc_title: Optional[str] = None,
) -> tuple[bool, Optional[int]]:
    """返回 (是否命中, 1-based 排名)。"""
    contains = (expect_contains or "").strip()
    title_kw = (expect_doc_title or "").strip()
    if not contains and not title_kw:
        return False, None
    for i, hit in enumerate(hits, start=1):
        content = str(hit.get("content") or "")
        meta = hit.get("metadata") or {}
        title = str(meta.get("title") or "")
        ok_content = (not contains) or (contains in content)
        ok_title = (not title_kw) or (title_kw in title)
        if ok_content and ok_title:
            return True, i
    return False, None
