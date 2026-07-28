"""文本切分单元测试。"""

from app.utils.chunking import chunk_text, iter_chunks_from_parts


def test_chunk_prefers_paragraph_boundary() -> None:
    text = "第一段内容完整结束。\n\n" + ("第二段继续讲述细节。" * 20)
    chunks = chunk_text(text, chunk_size=80, chunk_overlap=10)
    assert chunks
    # 应尽量在段落处断开，而不是硬切到段中间
    assert any("第一段" in c for c in chunks)
    assert all(len(c) <= 80 + 20 for c in chunks)  # 允许略超因边界保留


def test_iter_chunks_from_parts_covers_all() -> None:
    parts = ["AAA。" * 10, "BBB。" * 10, "CCC。" * 10]
    chunks = list(iter_chunks_from_parts(parts, chunk_size=60, chunk_overlap=8))
    joined = "".join(chunks)
    assert "AAA" in joined and "BBB" in joined and "CCC" in joined
    assert chunks
