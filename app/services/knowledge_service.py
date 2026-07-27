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
    KnowledgeSearchRequest,
)
from app.schemas.response.knowledge import (
    KnowledgeBaseResponse,
    KnowledgeDocumentResponse,
    KnowledgeSearchHit,
    KnowledgeSearchResponse,
)
from app.services.file_storage import FileStorageService
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

        for key, value in data.items():
            setattr(row, key, value)
        self.db.commit()
        self.db.refresh(row)
        return self._to_kb_response(row)

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
            text = extract_text(abs_path, doc.file_ext or "")
            log.info(
                f"[doc_id={doc.id}] 解析完成，文本长度={len(text)}，"
                f"耗时 {time.perf_counter() - t_parse:.1f}s"
            )

            self._update_progress(doc, "正在切分文本…")
            t_chunk = time.perf_counter()

            def _on_chunk(n: int, _piece: str) -> None:
                """每切出一块立即落库，供前端轮询刷新「分块」列。"""
                doc.chunk_count = n
                doc.parse_status = DocumentParseStatus.PROCESSING
                doc.error_message = f"正在切分文本 {n}…"[:500]
                self.db.commit()

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
        """切分结果向量化写入；大批量时分批 Embedding 并打进度日志。"""
        import time

        collection = kb_collection_name(kb.id)
        self.vector.ensure_collection(collection)
        total = len(chunks)
        t0 = time.perf_counter()
        log.info(f"[doc_id={doc.id}] 开始向量化入库，chunks={total}")

        embeddings: Optional[list[list[float]]] = None
        if kb.embedding_model_id:
            model_row = self.model_service.get_embedding_model_orm(kb.embedding_model_id)
            batch_size = max(1, min(self.settings.kb_embed_batch_size, 10))
            embeddings = []
            for start in range(0, total, batch_size):
                end = min(start + batch_size, total)
                batch = chunks[start:end]
                self._update_progress(
                    doc,
                    f"正在向量化 {end}/{total}（Embedding）…",
                )
                log.info(
                    f"[doc_id={doc.id}] Embedding 批次 {start + 1}-{end}/{total}"
                )
                embeddings.extend(embed_documents(model_row, batch))
        else:
            self._update_progress(doc, f"使用 Chroma 默认向量写入 {total} 块…")
            log.info(f"[doc_id={doc.id}] 未配置 Embedding，使用 Chroma 默认向量")

        documents = []
        for i, text in enumerate(chunks):
            documents.append(
                VectorDocument(
                    doc_id=f"doc_{doc.id}_chunk_{i}",
                    content=text,
                    metadata={
                        "knowledge_base_id": str(kb.id),
                        "document_id": str(doc.id),
                        "title": doc.title,
                        "chunk_index": i,
                    },
                    embedding=embeddings[i] if embeddings else None,
                )
            )

        # Chroma 分批写入，避免单次过大
        write_batch = 64
        for start in range(0, total, write_batch):
            end = min(start + write_batch, total)
            self._update_progress(doc, f"正在写入向量库 {end}/{total}…")
            self.vector._store.add_documents(collection, documents[start:end])
            log.info(f"[doc_id={doc.id}] Chroma 写入 {start + 1}-{end}/{total}")

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
        collection = kb_collection_name(kb.id)
        query_embedding: Optional[list[float]] = None
        if kb.embedding_model_id:
            model_row = self.model_service.get_embedding_model_orm(kb.embedding_model_id)
            query_embedding = embed_query(model_row, query)

        return self.vector.search(
            query=query,
            n_results=top_k,
            collection=collection,
            query_embedding=query_embedding,
        )

    @staticmethod
    def format_rag_context(hits: list[dict[str, Any]]) -> str:
        """将检索结果格式化为 system 上下文。"""
        if not hits:
            return ""
        parts = [
            "以下是知识库检索到的相关资料，请优先依据这些内容回答；"
            "若资料不足请明确说明，不要编造。"
        ]
        for i, hit in enumerate(hits, start=1):
            meta = hit.get("metadata") or {}
            title = meta.get("title") or "未命名"
            content = hit.get("content") or ""
            parts.append(f"[{i}] 来源《{title}》\n{content}")
        return "\n\n".join(parts)
