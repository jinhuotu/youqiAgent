"""知识库检索精炼与评测打分单测。"""

from app.services.kb_retrieve_refine import (
    expand_hits_with_neighbors,
    filter_by_max_distance,
    neighbor_chunk_ids,
    parse_chunk_id,
    score_eval_hit,
)


def test_parse_and_neighbor_ids() -> None:
    prefix, idx = parse_chunk_id("doc_9_chunk_3")
    assert prefix == "doc_9"
    assert idx == 3
    assert neighbor_chunk_ids("doc_9_chunk_3", 1) == ["doc_9_chunk_2", "doc_9_chunk_4"]
    assert neighbor_chunk_ids("doc_9_chunk_0", 1) == ["doc_9_chunk_1"]


def test_filter_by_max_distance() -> None:
    hits = [
        {"id": "a", "distance": 0.2},
        {"id": "b", "distance": 1.8},
        {"id": "c", "distance": None},
    ]
    kept = filter_by_max_distance(hits, 1.5)
    assert [h["id"] for h in kept] == ["a", "c"]
    assert len(filter_by_max_distance(hits, 0)) == 3


def test_expand_neighbors() -> None:
    primary = [{"id": "doc_1_chunk_2", "content": "mid", "distance": 0.1}]
    fetched = {
        "doc_1_chunk_1": {"id": "doc_1_chunk_1", "content": "left"},
        "doc_1_chunk_3": {"id": "doc_1_chunk_3", "content": "right"},
    }
    out = expand_hits_with_neighbors(primary, fetched, window=1, max_total=5)
    assert [h["id"] for h in out] == [
        "doc_1_chunk_2",
        "doc_1_chunk_1",
        "doc_1_chunk_3",
    ]


def test_score_eval_hit() -> None:
    hits = [
        {"content": "无关", "metadata": {"title": "A"}},
        {"content": "故障码 E12 处理步骤", "metadata": {"title": "维修手册"}},
    ]
    ok, rank = score_eval_hit(hits, expect_contains="E12", expect_doc_title="维修")
    assert ok and rank == 2
    ok2, rank2 = score_eval_hit(hits, expect_contains="不存在的词")
    assert not ok2 and rank2 is None
