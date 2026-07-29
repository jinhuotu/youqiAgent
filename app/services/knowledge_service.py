"""知识库业务服务：元数据 CRUD + 文件上传解析 + 切分入库 + 向量检索。"""

from typing import Any, Optional

from fastapi import UploadFile
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.context import get_current_role, get_current_user_id
from app.core.exceptions import BusinessError, ForbiddenError, NotFoundError
from app.core.logger import get_logger
from app.db.mysql.models.knowledge import (
    DocumentParseStatus,
    DocumentSourceType,
    KnowledgeBase,
    KnowledgeDocument,
    KnowledgeScope,
)
from app.db.vector.base import VectorDocument
from app.schemas.request.knowledge import (
    KnowledgeBaseCreateRequest,
    KnowledgeBaseUpdateRequest,
    KnowledgeDocumentCreateRequest,
    KnowledgeEvalRequest,
    KnowledgeSearchRequest,
)
from app.schemas.response.knowledge import (
    KnowledgeBaseResponse,
    KnowledgeDocumentResponse,
    KnowledgeEvalCaseResult,
    KnowledgeEvalResponse,
    KnowledgeSearchHit,
    KnowledgeSearchResponse,
)
from app.services.file_storage import FileStorageService
from app.services.kb_retrieve_refine import (
    expand_hits_with_neighbors,
    filter_by_max_distance,
    neighbor_chunk_ids,
    score_eval_hit,
)
from app.services.llm.embedding import embed_documents, embed_query
from app.services.model_service import ModelService
from app.services.parsers import extract_text
from app.services.vector_service import VectorService
from app.utils.chunking import chunk_text

log = get_logger("services.knowledge")


def kb_collection_name(knowledge_base_id: int) -> str:
    """知识库对应的 Chroma 集合名。"""
    return f"kb_{knowledge_base_id}"


class KnowledgeService:
    """知识库业务逻辑。"""

    def __init__(self, db: Session) -> None:
        self.db = db
        self.settings = get_settings()
        self.model_service = ModelService(db)
        self.vector = VectorService()
        self.storage = FileStorageService()

    # -------------------- 可见性 --------------------

    def _visible_kb_query(self, user_id: str):
        return select(KnowledgeBase).where(
            or_(
                KnowledgeBase.scope == KnowledgeScope.PUBLIC,
                (KnowledgeBase.scope == KnowledgeScope.PRIVATE)
                & (KnowledgeBase.user_id == user_id),
            )
        )

    def _get_accessible_kb(self, kb_id: int) -> KnowledgeBase:
        user_id = get_current_user_id()
        row = self.db.get(KnowledgeBase, kb_id)
        if row is None:
            raise NotFoundError("知识库不存在")
        if row.scope == KnowledgeScope.PRIVATE and row.user_id != user_id:
            raise NotFoundError("知识库不存在")
        return row

    def _assert_kb_manageable(self, row: KnowledgeBase) -> None:
        user_id = get_current_user_id()
        role = get_current_role()
        if row.scope == KnowledgeScope.PUBLIC:
            if not self.settings.enable_admin_role or role != "admin":
                raise ForbiddenError("仅管理员可管理公共知识库")
            return
        if row.user_id != user_id:
            raise ForbiddenError("无权操作该知识库")

    def _document_count(self, kb_id: int) -> int:
        return int(
            self.db.scalar(
                select(func.count())
                .select_from(KnowledgeDocument)
                .where(
                    KnowledgeDocument.knowledge_base_id == kb_id,
                    KnowledgeDocument.status == 1,
                )
            )
            or 0
        )

    def _to_kb_response(self, row: KnowledgeBase) -> KnowledgeBaseResponse:
        return KnowledgeBaseResponse(
            id=row.id,
            name=row.name,
            description=row.description,
            scope=row.scope,
            embedding_model_id=row.embedding_model_id,
            user_id=row.user_id,
            status=row.status,
            document_count=self._document_count(row.id),
            create_time=row.create_time,
            update_time=row.update_time,
        )

    def _to_doc_response(self, row: KnowledgeDocument) -> KnowledgeDocumentResponse:
        return KnowledgeDocumentResponse.model_validate(row)

    def _owner_user_id(self, kb: KnowledgeBase) -> str:
        user_id = get_current_user_id()
        return user_id if kb.scope == KnowledgeScope.PRIVATE else kb.user_id

    # -------------------- 知识库 CRUD --------------------

    def list_knowledge_bases(self) -> list[KnowledgeBaseResponse]:
        user_id = get_current_user_id()
        rows = self.db.scalars(
            self._visible_kb_query(user_id).order_by(KnowledgeBase.id.desc())
        ).all()
        return [self._to_kb_response(r) for r in rows]

    def get_knowledge_base(self, kb_id: int) -> KnowledgeBaseResponse:
        return self._to_kb_response(self._get_accessible_kb(kb_id))

    def create_knowledge_base(self, req: KnowledgeBaseCreateRequest) -> KnowledgeBaseResponse:
        user_id = get_current_user_id()
        role = get_current_role()

        if req.scope == KnowledgeScope.PUBLIC:
            if not self.settings.enable_admin_role or role != "admin":
                raise ForbiddenError("仅管理员可创建公共知识库")
            owner_id = "0"
        else:
            owner_id = user_id

        if req.embedding_model_id is not None:
            self.model_service.get_embedding_model_orm(req.embedding_model_id)

        row = KnowledgeBase(
            name=req.name,
            description=req.description,
            scope=req.scope,
            embedding_model_id=req.embedding_model_id,
            user_id=owner_id,
            status=req.status,
        )
        self.db.add(row)
        self.db.commit()
        self.db.refresh(row)

        self.vector.init_knowledge_base()
        self.vector.ensure_collection(
            kb_collection_name(row.id),
            metadata={"kb_id": str(row.id), "name": row.name},
        )
        log.info(f"创建知识库成功: id={row.id}, name={row.name}")
        return self._to_kb_response(row)

    def update_knowledge_base(
        self,
        kb_id: int,
        req: KnowledgeBaseUpdateRequest,
    ) -> KnowledgeBaseResponse:
        row = self._get_accessible_kb(kb_id)
        self._assert_kb_manageable(row)

        data = req.model_dump(exclude_unset=True)
        if "scope" in data and data["scope"] == KnowledgeScope.PUBLIC:
            role = get_current_role()
            if not self.settings.enable_admin_role or role != "admin":
                raise ForbiddenError("仅管理员可将知识库设为公共")
            row.user_id = "0"

        if "embedding_model_id" in data and data["embedding_model_id"] is not None:
            self.model_service.get_embedding_model_orm(data["embedding_model_id"])

        old_embedding_id = row.embedding_model_id
        embedding_changed = (
            "embedding_model_id" in data and data["embedding_model_id"] != old_embedding_id
        )

        for key, value in data.items():
            setattr(row, key, value)
        self.db.commit()
        self.db.refresh(row)

        if embedding_changed:
            requeued = self._reindex_after_embedding_change(row)
            log.info(
                f"知识库 Embedding 变更: kb_id={row.id}, "
                f"{old_embedding_id} -> {row.embedding_model_id}, requeued={requeued}"
            )
        return self._to_kb_response(row)

    def _reindex_after_embedding_change(self, kb: KnowledgeBase) -> int:
        """Embedding 变更后清空旧向量，并将文档重新入库。"""
        from app.services.kb_job_queue import enqueue_document_job
        from app.utils.chunking import chunk_text

        collection = kb_collection_name(kb.id)
        self.vector.delete_collection(collection)
        self.vector.ensure_collection(
            collection,
            metadata={"kb_id": str(kb.id), "name": kb.name},
        )

        docs = self.db.scalars(
            select(KnowledgeDocument).where(
                KnowledgeDocument.knowledge_base_id == kb.id,
                KnowledgeDocument.status == 1,
            )
        ).all()
        requeued = 0
        for doc in docs:
            if doc.source_type == DocumentSourceType.FILE and doc.file_path:
                doc.parse_status = DocumentParseStatus.PROCESSING
                doc.error_message = "Embedding 已变更，等待重新向量化…"
                doc.chunk_count = 0
                self.db.commit()
                enqueue_document_job(doc.id, force=True)
                requeued += 1
            elif (doc.content or "").strip():
                try:
                    chunks = chunk_text(doc.content)
                    if not chunks:
                        doc.parse_status = DocumentParseStatus.FAILED
                        doc.error_message = "Embedding 变更后切分结果为空"
                        self.db.commit()
                        continue
                    doc.chunk_count = len(chunks)
                    self.db.commit()
                    self._index_chunks(kb, doc, chunks)
                    doc.parse_status = DocumentParseStatus.READY
                    doc.error_message = None
                    self.db.commit()
                    requeued += 1
                except Exception as e:
                    log.exception(f"[doc_id={doc.id}] Embedding 变更后重建失败: {e}")
                    doc.parse_status = DocumentParseStatus.FAILED
                    doc.error_message = f"Embedding 变更重建失败: {str(e)[:200]}"
                    self.db.commit()
        return requeued

    def delete_knowledge_base(self, kb_id: int) -> None:
        row = self._get_accessible_kb(kb_id)
        self._assert_kb_manageable(row)

        docs = self.db.scalars(
            select(KnowledgeDocument).where(KnowledgeDocument.knowledge_base_id == kb_id)
        ).all()
        for doc in docs:
            self.storage.delete_file(doc.file_path)
            self.db.delete(doc)
        self.db.delete(row)
        self.db.commit()
        self.vector.delete_collection(kb_collection_name(kb_id))
        log.info(f"删除知识库: id={kb_id}")

    # -------------------- 文档 --------------------

    def list_documents(self, kb_id: int) -> list[KnowledgeDocumentResponse]:
        self._get_accessible_kb(kb_id)
        rows = self.db.scalars(
            select(KnowledgeDocument)
            .where(
                KnowledgeDocument.knowledge_base_id == kb_id,
                KnowledgeDocument.status == 1,
            )
            .order_by(KnowledgeDocument.id.desc())
        ).all()
        return [self._to_doc_response(r) for r in rows]

    def add_document(
        self,
        kb_id: int,
        req: KnowledgeDocumentCreateRequest,
    ) -> KnowledgeDocumentResponse:
        kb = self._get_accessible_kb(kb_id)
        self._assert_kb_manageable(kb)
        if kb.status != 1:
            raise BusinessError("知识库已禁用，无法录入文档")

        doc = self._ingest_text(
            kb=kb,
            title=req.title,
            content=req.content,
            source_type=DocumentSourceType.TEXT,
        )
        return self._to_doc_response(doc)

    async def upload_documents(
        self,
        kb_id: int,
        files: list[UploadFile],
    ) -> list[KnowledgeDocumentResponse]:
        """多文件上传：仅落盘并创建 processing 记录，解析/向量化由后台任务完成。

        Returns:
            已创建的文档列表（parse_status=processing 或落盘失败的 failed）
        """
        kb = self._get_accessible_kb(kb_id)
        self._assert_kb_manageable(kb)
        if kb.status != 1:
            raise BusinessError("知识库已禁用，无法上传文档")

        self.storage.validate_batch_count(len(files))
        results: list[KnowledgeDocumentResponse] = []

        for upload in files:
            saved = None
            try:
                log.info(
                    f"[upload] 开始接收文件 kb_id={kb_id}, "
                    f"filename={upload.filename}"
                )
                saved = await self.storage.save_upload(kb_id, upload)
                title = saved.original_name[:256]
                doc = KnowledgeDocument(
                    knowledge_base_id=kb_id,
                    title=title,
                    content="",
                    chunk_count=0,
                    source_type=DocumentSourceType.FILE,
                    file_name=saved.original_name,
                    file_path=saved.relative_path,
                    file_ext=saved.ext,
                    file_size=saved.size,
                    parse_status=DocumentParseStatus.PROCESSING,
                    error_message="已落盘，等待后台解析…",
                    user_id=self._owner_user_id(kb),
                    status=1,
                )
                self.db.add(doc)
                self.db.commit()
                self.db.refresh(doc)
                log.info(
                    f"[upload] 落盘完成 doc_id={doc.id}, kb_id={kb_id}, "
                    f"file={saved.original_name}, size={saved.size}, path={saved.relative_path}"
                )
                results.append(self._to_doc_response(doc))
            except Exception as e:
                message = str(e)[:500]
                # 参数类错误不打堆栈，避免刷屏
                from app.core.exceptions import AppException

                if isinstance(e, AppException):
                    log.warning(
                        f"[upload] 文件接收失败 kb_id={kb_id}, "
                        f"file={getattr(upload, 'filename', None)}, error={message}"
                    )
                else:
                    log.exception(
                        f"[upload] 文件接收异常 kb_id={kb_id}, "
                        f"file={getattr(upload, 'filename', None)}, error={e}"
                    )
                if saved is not None:
                    self.storage.delete_file(saved.relative_path)
                failed = KnowledgeDocument(
                    knowledge_base_id=kb_id,
                    title=(upload.filename or "unknown")[:256],
                    content="",
                    chunk_count=0,
                    source_type=DocumentSourceType.FILE,
                    file_name=upload.filename,
                    file_path=None,
                    file_ext=None,
                    file_size=None,
                    parse_status=DocumentParseStatus.FAILED,
                    error_message=message,
                    user_id=self._owner_user_id(kb),
                    status=1,
                )
                self.db.add(failed)
                self.db.commit()
                self.db.refresh(failed)
                results.append(self._to_doc_response(failed))

        return results

    def _update_progress(self, doc: KnowledgeDocument, message: str) -> None:
        """更新处理进度（复用 error_message 字段展示进度文案）。"""
        doc.parse_status = DocumentParseStatus.PROCESSING
        doc.error_message = message[:500]
        self.db.commit()
        log.info(f"[doc_id={doc.id}] {message}")

    def process_uploaded_document(self, doc_id: int) -> None:
        """后台处理单个已上传文档：解析 → 切分 → Embedding → 向量库。"""
        import time

        t0 = time.perf_counter()
        doc = self.db.get(KnowledgeDocument, doc_id)
        if doc is None:
            log.warning(f"[doc_id={doc_id}] 文档不存在，跳过后台处理")
            return
        if doc.parse_status == DocumentParseStatus.READY:
            log.info(f"[doc_id={doc_id}] 已是 ready，跳过")
            return
        if not doc.file_path:
            doc.parse_status = DocumentParseStatus.FAILED
            doc.error_message = "缺少本地文件路径"
            self.db.commit()
            return

        kb = self.db.get(KnowledgeBase, doc.knowledge_base_id)
        if kb is None:
            doc.parse_status = DocumentParseStatus.FAILED
            doc.error_message = "所属知识库不存在"
            self.db.commit()
            return

        try:
            abs_path = self.storage.resolve_absolute(doc.file_path)
            self._update_progress(doc, f"正在解析文件（{doc.file_ext}）…")
            t_parse = time.perf_counter()
            ext = (doc.file_ext or "").lower().lstrip(".")

            self._update_progress(doc, "正在切分文本…")
            t_chunk = time.perf_counter()
            progress_every = max(1, self.settings.kb_chunk_progress_every)

            def _on_chunk(n: int, _piece: str) -> None:
                """按间隔落库进度，避免大文件每块都 commit。"""
                if n == 1 or n % progress_every == 0:
                    doc.chunk_count = n
                    doc.parse_status = DocumentParseStatus.PROCESSING
                    doc.error_message = f"正在切分文本 {n}…"[:500]
                    self.db.commit()

            if ext == "pdf":
                from app.services.parsers.pdf_parser import iter_pdf_page_texts
                from app.utils.chunking import iter_chunks_from_parts

                page_texts: list[str] = []

                def _pages():
                    for p in iter_pdf_page_texts(abs_path):
                        page_texts.append(p)
                        yield p

                chunks = list(iter_chunks_from_parts(_pages(), on_chunk=_on_chunk))
                text = "\n\n".join(page_texts)
                log.info(
                    f"[doc_id={doc.id}] PDF 解析+切分完成，页数={len(page_texts)}，"
                    f"文本长度={len(text)}，耗时 {time.perf_counter() - t_parse:.1f}s"
                )
            else:
                text = extract_text(abs_path, doc.file_ext or "")
                log.info(
                    f"[doc_id={doc.id}] 解析完成，文本长度={len(text)}，"
                    f"耗时 {time.perf_counter() - t_parse:.1f}s"
                )
                chunks = chunk_text(text, on_chunk=_on_chunk)

            if not chunks:
                raise BusinessError("解析结果为空，无法入库（可能是扫描版 PDF，本期不支持 OCR）")
            doc.content = text
            doc.chunk_count = len(chunks)
            self.db.commit()
            log.info(
                f"[doc_id={doc.id}] 切分完成，chunks={len(chunks)}，"
                f"耗时 {time.perf_counter() - t_chunk:.1f}s"
            )

            self._index_chunks(kb, doc, chunks)
            doc.parse_status = DocumentParseStatus.READY
            doc.error_message = None
            self.db.commit()
            log.info(
                f"[doc_id={doc.id}] 全部完成，总耗时 {time.perf_counter() - t0:.1f}s，"
                f"file={doc.file_name}, chunks={doc.chunk_count}"
            )
        except Exception as e:
            message = str(e)[:500]
            from app.core.exceptions import AppException

            if isinstance(e, AppException):
                log.error(f"[doc_id={doc_id}] 处理失败: {message}")
            else:
                log.exception(f"[doc_id={doc_id}] 处理异常: {e}")
            # flush 失败后 Session 处于 PendingRollback，必须先 rollback 再写失败状态
            try:
                self.db.rollback()
            except Exception:
                pass
            failed = self.db.get(KnowledgeDocument, doc_id)
            if failed is None:
                return
            failed.parse_status = DocumentParseStatus.FAILED
            failed.error_message = message
            if not failed.content:
                failed.content = ""
            self.db.commit()

    def _ingest_text(
        self,
        *,
        kb: KnowledgeBase,
        title: str,
        content: str,
        source_type: DocumentSourceType = DocumentSourceType.TEXT,
        file_name: Optional[str] = None,
        file_path: Optional[str] = None,
        file_ext: Optional[str] = None,
        file_size: Optional[int] = None,
    ) -> KnowledgeDocument:
        """文本入库公共逻辑。"""
        chunks = chunk_text(content)
        if not chunks:
            raise BusinessError("文档内容为空，无法入库")

        doc = KnowledgeDocument(
            knowledge_base_id=kb.id,
            title=title,
            content=content,
            chunk_count=len(chunks),
            source_type=source_type,
            file_name=file_name,
            file_path=file_path,
            file_ext=file_ext,
            file_size=file_size,
            parse_status=DocumentParseStatus.PROCESSING,
            error_message=None,
            user_id=self._owner_user_id(kb),
            status=1,
        )
        self.db.add(doc)
        self.db.commit()
        self.db.refresh(doc)

        try:
            self._index_chunks(kb, doc, chunks)
            doc.parse_status = DocumentParseStatus.READY
            self.db.commit()
            self.db.refresh(doc)
        except Exception as e:
            self.storage.delete_file(doc.file_path)
            self.db.delete(doc)
            self.db.commit()
            log.exception(f"文档向量入库失败: kb_id={kb.id}, error={e}")
            raise BusinessError(f"文档向量入库失败: {e}") from e

        log.info(
            f"文档入库成功: kb_id={kb.id}, doc_id={doc.id}, chunks={doc.chunk_count}"
        )
        return doc

    def delete_document(self, kb_id: int, doc_id: int) -> None:
        kb = self._get_accessible_kb(kb_id)
        self._assert_kb_manageable(kb)
        doc = self.db.get(KnowledgeDocument, doc_id)
        if doc is None or doc.knowledge_base_id != kb_id:
            raise NotFoundError("文档不存在")

        chunk_ids = [f"doc_{doc.id}_chunk_{i}" for i in range(doc.chunk_count)]
        if chunk_ids:
            self.vector.delete(chunk_ids, collection=kb_collection_name(kb_id))
        self.storage.delete_file(doc.file_path)
        self.db.delete(doc)
        self.db.commit()
        log.info(f"删除文档: kb_id={kb_id}, doc_id={doc_id}")

    def _index_chunks(
        self,
        kb: KnowledgeBase,
        doc: KnowledgeDocument,
        chunks: list[str],
    ) -> None:
        """切分结果向量化写入；按批 Embedding + 立即写入，避免全集文档驻留内存。"""
        import time

        collection = kb_collection_name(kb.id)
        self.vector.ensure_collection(collection)
        total = len(chunks)
        t0 = time.perf_counter()
        log.info(f"[doc_id={doc.id}] 开始向量化入库，chunks={total}")

        model_row = None
        if kb.embedding_model_id:
            model_row = self.model_service.get_embedding_model_orm(kb.embedding_model_id)

        batch_size = max(1, min(self.settings.kb_embed_batch_size, 10))
        write_batch = 64
        pending: list[VectorDocument] = []

        def _flush(pending_docs: list[VectorDocument], end_idx: int) -> None:
            if not pending_docs:
                return
            self._update_progress(doc, f"正在写入向量库 {end_idx}/{total}…")
            self.vector._store.add_documents(collection, pending_docs)
            log.info(
                f"[doc_id={doc.id}] Chroma 写入至 {end_idx}/{total}（本批 {len(pending_docs)}）"
            )
            pending_docs.clear()

        for start in range(0, total, batch_size):
            end = min(start + batch_size, total)
            batch = chunks[start:end]
            if model_row is not None:
                self._update_progress(doc, f"正在向量化 {end}/{total}（Embedding）…")
                log.info(f"[doc_id={doc.id}] Embedding 批次 {start + 1}-{end}/{total}")
                vectors = embed_documents(model_row, batch)
            else:
                if start == 0:
                    self._update_progress(doc, f"使用 Chroma 默认向量写入 {total} 块…")
                    log.info(f"[doc_id={doc.id}] 未配置 Embedding，使用 Chroma 默认向量")
                vectors = [None] * len(batch)

            for offset, text in enumerate(batch):
                i = start + offset
                pending.append(
                    VectorDocument(
                        doc_id=f"doc_{doc.id}_chunk_{i}",
                        content=text,
                        metadata={
                            "knowledge_base_id": str(kb.id),
                            "document_id": str(doc.id),
                            "title": doc.title,
                            "chunk_index": i,
                        },
                        embedding=vectors[offset],
                    )
                )
            if len(pending) >= write_batch:
                _flush(pending, end)

        _flush(pending, total)
        elapsed = time.perf_counter() - t0
        log.info(f"[doc_id={doc.id}] 向量化入库完成，耗时 {elapsed:.1f}s，chunks={total}")

    # -------------------- 检索 / RAG --------------------

    def search(
        self,
        kb_id: int,
        req: KnowledgeSearchRequest,
    ) -> KnowledgeSearchResponse:
        kb = self._get_accessible_kb(kb_id)
        if kb.status != 1:
            raise BusinessError("知识库已禁用")

        hits = self._retrieve(kb, req.query, req.top_k)
        return KnowledgeSearchResponse(
            query=req.query,
            top_k=req.top_k,
            max_distance=float(self.settings.kb_rag_max_distance),
            neighbor_window=int(self.settings.kb_neighbor_window),
            hits=[
                KnowledgeSearchHit(
                    id=str(h.get("id", "")),
                    content=str(h.get("content", "")),
                    distance=h.get("distance"),
                    metadata=h.get("metadata") or {},
                )
                for h in hits
            ],
        )

    def retrieve_for_rag(
        self,
        kb_id: int,
        query: str,
        top_k: Optional[int] = None,
    ) -> list[dict[str, Any]]:
        """供对话注入使用的检索入口。"""
        kb = self._get_accessible_kb(kb_id)
        if kb.status != 1:
            raise BusinessError("知识库已禁用，无法用于 RAG")
        k = top_k or self.settings.kb_default_top_k
        return self._retrieve(kb, query, k)

    def _retrieve(
        self,
        kb: KnowledgeBase,
        query: str,
        top_k: int,
    ) -> list[dict[str, Any]]:
        """向量召回 + 距离门槛 + 邻块扩展。"""
        collection = kb_collection_name(kb.id)
        query_embedding: Optional[list[float]] = None
        if kb.embedding_model_id:
            model_row = self.model_service.get_embedding_model_orm(kb.embedding_model_id)
            query_embedding = embed_query(model_row, query)

        max_distance = float(self.settings.kb_rag_max_distance)
        window = int(self.settings.kb_neighbor_window)
        mult = int(self.settings.kb_retrieve_candidate_multiplier)
        candidate_n = max(top_k, top_k * mult if max_distance > 0 else top_k)
        candidate_n = min(50, candidate_n)

        raw = self.vector.search(
            query=query,
            n_results=candidate_n,
            collection=collection,
            query_embedding=query_embedding,
        )
        filtered = filter_by_max_distance(raw, max_distance)
        primary = filtered[:top_k]
        if not primary:
            return []

        if window <= 0:
            return primary

        neighbor_ids: list[str] = []
        for hit in primary:
            neighbor_ids.extend(neighbor_chunk_ids(str(hit.get("id") or ""), window))
        # 去重且排除已在 primary 中的
        primary_ids = {str(h.get("id") or "") for h in primary}
        neighbor_ids = [i for i in dict.fromkeys(neighbor_ids) if i and i not in primary_ids]
        fetched: list[dict[str, Any]] = []
        if neighbor_ids:
            try:
                fetched = self.vector.get_by_ids(neighbor_ids, collection=collection)
            except Exception as e:
                log.warning(f"邻块读取失败，将仅返回主命中: {e}")
                fetched = []
        by_id = {str(d.get("id")): d for d in fetched if d.get("id")}
        max_total = min(20, top_k * (1 + 2 * window))
        return expand_hits_with_neighbors(
            primary,
            by_id,
            window=window,
            max_total=max_total,
        )

    def evaluate_retrieval(
        self,
        kb_id: int,
        req: KnowledgeEvalRequest,
    ) -> KnowledgeEvalResponse:
        """黄金集语义检索评测（命中率 / MRR）。"""
        kb = self._get_accessible_kb(kb_id)
        if kb.status != 1:
            raise BusinessError("知识库已禁用")

        case_results: list[KnowledgeEvalCaseResult] = []
        hit_count = 0
        mrr_sum = 0.0
        for case in req.cases:
            hits = self._retrieve(kb, case.query, req.top_k)
            ok, rank = score_eval_hit(
                hits,
                expect_contains=case.expect_contains,
                expect_doc_title=case.expect_doc_title,
            )
            if ok:
                hit_count += 1
                if rank:
                    mrr_sum += 1.0 / float(rank)
            reason = "命中" if ok else "未命中"
            if not (case.expect_contains or "").strip() and not (case.expect_doc_title or "").strip():
                reason = "缺少 expect_contains / expect_doc_title"
            case_results.append(
                KnowledgeEvalCaseResult(
                    query=case.query,
                    hit=ok,
                    hit_at=rank,
                    reason=reason,
                    top_ids=[str(h.get("id") or "") for h in hits[:5]],
                    top_distances=[
                        float(h["distance"]) if h.get("distance") is not None else None
                        for h in hits[:5]
                    ],
                )
            )
        total = len(req.cases)
        return KnowledgeEvalResponse(
            total=total,
            hit_count=hit_count,
            hit_rate=(hit_count / total) if total else 0.0,
            mrr=(mrr_sum / total) if total else 0.0,
            top_k=req.top_k,
            max_distance=float(self.settings.kb_rag_max_distance),
            neighbor_window=int(self.settings.kb_neighbor_window),
            cases=case_results,
        )

    @staticmethod
    def format_rag_context(hits: list[dict[str, Any]]) -> str:
        """将检索结果格式化为 system 上下文。"""
        if not hits:
            return ""
        parts = [
            "以下是知识库检索到的相关资料，请优先依据这些内容回答；"
            "若资料不足请明确说明，不要编造。"
            "回答时可自然引用资料编号（如「根据资料[1]」）。"
        ]
        for i, hit in enumerate(hits, start=1):
            meta = hit.get("metadata") or {}
            title = meta.get("title") or "未命名"
            content = hit.get("content") or ""
            parts.append(f"[{i}] 来源《{title}》\n{content}")
        return "\n\n".join(parts)

    @staticmethod
    def hits_to_sources(
        hits: list[dict[str, Any]],
        *,
        preview_chars: int = 240,
    ) -> list[dict[str, Any]]:
        """将检索命中转为前端可展示的引用来源。"""
        sources: list[dict[str, Any]] = []
        limit = max(40, preview_chars)
        for hit in hits:
            meta = hit.get("metadata") or {}
            content = str(hit.get("content") or "")
            preview = content if len(content) <= limit else content[:limit].rstrip() + "…"
            doc_id_raw = meta.get("document_id")
            chunk_raw = meta.get("chunk_index")
            try:
                document_id = int(doc_id_raw) if doc_id_raw is not None else None
            except (TypeError, ValueError):
                document_id = None
            try:
                chunk_index = int(chunk_raw) if chunk_raw is not None else None
            except (TypeError, ValueError):
                chunk_index = None
            distance = hit.get("distance")
            try:
                distance_f = float(distance) if distance is not None else None
            except (TypeError, ValueError):
                distance_f = None
            sources.append(
                {
                    "id": str(hit.get("id") or ""),
                    "title": str(meta.get("title") or "未命名"),
                    "content": preview,
                    "document_id": document_id,
                    "chunk_index": chunk_index,
                    "distance": distance_f,
                }
            )
        return sources
