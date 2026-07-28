"""知识库文档处理任务队列（基于 Redis List）。

上传接口只入队；独立 worker 线程消费，进程重启后可从 Redis / MySQL 恢复。
Redis 不可用时降级为临时线程，保证开发环境可继续用。
"""

from __future__ import annotations

import threading
import time
from datetime import datetime, timedelta

from app.core.config import get_settings
from app.core.logger import get_logger
from app.db.mysql.models.knowledge import (
    DocumentParseStatus,
    DocumentSourceType,
    KnowledgeDocument,
)
from app.db.mysql.session import get_session_factory
from app.db.redis import check_redis_connection, get_redis
from app.services.knowledge_service import KnowledgeService

log = get_logger("services.kb_job_queue")

QUEUE_KEY = "ai:kb:doc:queue"
QUEUED_SET_KEY = "ai:kb:doc:queued"

_stop_event = threading.Event()
_workers: list[threading.Thread] = []
_lock = threading.Lock()


def enqueue_document_job(doc_id: int, *, force: bool = False) -> bool:
    """将文档处理任务入队。

    Args:
        doc_id: 文档 ID
        force: True 时忽略已在队列标记，强制重新入队（用于恢复卡住任务）

    Returns:
        True 表示已入队或已在队列中；False 表示入队失败且已降级到临时线程。
    """
    doc_key = str(doc_id)
    if check_redis_connection():
        try:
            client = get_redis()
            if force:
                client.srem(QUEUED_SET_KEY, doc_key)
            added = client.sadd(QUEUED_SET_KEY, doc_key)
            if added:
                client.lpush(QUEUE_KEY, doc_key)
                log.info(f"[doc_id={doc_id}] 已入队 Redis 知识库任务队列")
            else:
                log.info(f"[doc_id={doc_id}] 已在队列中，跳过重复入队")
            return True
        except Exception as e:
            log.warning(f"[doc_id={doc_id}] Redis 入队失败，降级临时线程: {e}")

    _spawn_fallback_thread(doc_id)
    return False


def _spawn_fallback_thread(doc_id: int) -> None:
    """Redis 不可用时的降级路径。"""
    thread = threading.Thread(
        target=_process_one,
        args=(doc_id,),
        name=f"kb-fallback-{doc_id}",
        daemon=True,
    )
    thread.start()
    log.warning(f"[doc_id={doc_id}] 已启动降级处理线程 {thread.name}")


def _process_one(doc_id: int) -> None:
    """处理单个文档（独立 DB Session）。"""
    db = get_session_factory()()
    try:
        KnowledgeService(db).process_uploaded_document(doc_id)
    except Exception as e:
        log.exception(f"[doc_id={doc_id}] 队列任务未捕获异常: {e}")
    finally:
        db.close()
        _clear_queued_mark(doc_id)


def _clear_queued_mark(doc_id: int) -> None:
    try:
        if check_redis_connection():
            get_redis().srem(QUEUED_SET_KEY, str(doc_id))
    except Exception as e:
        log.warning(f"[doc_id={doc_id}] 清理队列标记失败: {e}")


def _worker_loop(worker_id: int) -> None:
    """阻塞消费 Redis 队列。"""
    log.info(f"知识库任务 worker-{worker_id} 已启动")
    while not _stop_event.is_set():
        try:
            if not check_redis_connection():
                time.sleep(2)
                continue
            client = get_redis()
            item = client.brpop(QUEUE_KEY, timeout=2)
            if not item:
                continue
            _, doc_key = item
            doc_id = int(doc_key)
            log.info(f"worker-{worker_id} 开始处理 doc_id={doc_id}")
            _process_one(doc_id)
        except Exception as e:
            log.exception(f"worker-{worker_id} 循环异常: {e}")
            time.sleep(1)
    log.info(f"知识库任务 worker-{worker_id} 已停止")


def recover_stuck_jobs() -> int:
    """将卡住的 processing / 未完成 file 文档重新入队。"""
    settings = get_settings()
    stuck_before = datetime.now() - timedelta(minutes=settings.kb_job_stuck_minutes)
    db = get_session_factory()()
    recovered = 0
    try:
        rows = (
            db.query(KnowledgeDocument)
            .filter(
                KnowledgeDocument.source_type == DocumentSourceType.FILE,
                KnowledgeDocument.parse_status.in_(
                    [DocumentParseStatus.PROCESSING, DocumentParseStatus.PENDING]
                ),
                KnowledgeDocument.file_path.isnot(None),
            )
            .all()
        )
        for row in rows:
            # pending 全部重入队；processing 仅超过阈值才重入队
            if row.parse_status == DocumentParseStatus.PROCESSING:
                ts = row.update_time or row.create_time
                if ts and ts > stuck_before:
                    continue
            enqueue_document_job(row.id, force=True)
            recovered += 1
            log.warning(
                f"[doc_id={row.id}] 恢复卡住任务 status={row.parse_status.value}"
            )
    except Exception as e:
        log.exception(f"恢复卡住知识库任务失败: {e}")
    finally:
        db.close()
    return recovered


def start_workers() -> None:
    """启动队列消费者（幂等）。"""
    global _workers
    with _lock:
        if _workers:
            return
        _stop_event.clear()
        settings = get_settings()
        n = max(1, settings.kb_job_workers)
        for i in range(n):
            t = threading.Thread(
                target=_worker_loop,
                args=(i + 1,),
                name=f"kb-queue-worker-{i + 1}",
                daemon=True,
            )
            t.start()
            _workers.append(t)
        log.info(f"知识库任务队列已启动 workers={n}")


def stop_workers() -> None:
    """通知 worker 退出。"""
    global _workers
    _stop_event.set()
    with _lock:
        _workers = []
    log.info("知识库任务队列停止信号已发送")
