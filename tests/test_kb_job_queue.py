"""知识库任务队列入队逻辑测试。"""

from unittest.mock import MagicMock

import app.services.kb_job_queue as queue


def test_enqueue_document_job_pushes_redis(monkeypatch) -> None:
    client = MagicMock()
    client.sadd.return_value = 1
    monkeypatch.setattr(queue, "check_redis_connection", lambda: True)
    monkeypatch.setattr(queue, "get_redis", lambda: client)

    ok = queue.enqueue_document_job(42)
    assert ok is True
    client.sadd.assert_called_once_with(queue.QUEUED_SET_KEY, "42")
    client.lpush.assert_called_once_with(queue.QUEUE_KEY, "42")


def test_enqueue_skips_duplicate(monkeypatch) -> None:
    client = MagicMock()
    client.sadd.return_value = 0
    monkeypatch.setattr(queue, "check_redis_connection", lambda: True)
    monkeypatch.setattr(queue, "get_redis", lambda: client)

    ok = queue.enqueue_document_job(7)
    assert ok is True
    client.lpush.assert_not_called()


def test_enqueue_force_requeues(monkeypatch) -> None:
    client = MagicMock()
    client.sadd.return_value = 1
    monkeypatch.setattr(queue, "check_redis_connection", lambda: True)
    monkeypatch.setattr(queue, "get_redis", lambda: client)

    ok = queue.enqueue_document_job(9, force=True)
    assert ok is True
    client.srem.assert_called_once_with(queue.QUEUED_SET_KEY, "9")
    client.lpush.assert_called_once_with(queue.QUEUE_KEY, "9")
