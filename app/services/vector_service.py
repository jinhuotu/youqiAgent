"""向量库业务服务层。

所有向量操作统一通过本层调用，后续切换向量库仅需替换实现类。
本期预留知识库集合，提供基础增删查接口，暂不绑定具体业务。
"""

from typing import Any, Optional

from app.core.logger import get_logger
from app.db.vector.base import VectorDocument
from app.db.vector.chroma_impl import get_vector_store

log = get_logger("services.vector")

# 预留知识库集合名
DEFAULT_KNOWLEDGE_COLLECTION = "knowledge_base"


class VectorService:
    """向量数据库业务封装。"""

    def __init__(self) -> None:
        self._store = get_vector_store()

    def init_knowledge_base(self) -> None:
        """初始化预留知识库集合。"""
        self._store.ensure_collection(
            DEFAULT_KNOWLEDGE_COLLECTION,
            metadata={"description": "预留知识库集合，暂不绑定业务"},
        )
        log.info("知识库集合已就绪")

    def ensure_collection(
        self,
        collection: str = DEFAULT_KNOWLEDGE_COLLECTION,
        metadata: Optional[dict] = None,
    ) -> None:
        """确保集合存在。"""
        self._store.ensure_collection(collection, metadata)

    def add(
        self,
        doc_id: str,
        content: str,
        metadata: Optional[dict[str, Any]] = None,
        collection: str = DEFAULT_KNOWLEDGE_COLLECTION,
    ) -> str:
        """新增文档。"""
        self._store.ensure_collection(collection)
        ids = self._store.add_documents(
            collection,
            [VectorDocument(doc_id=doc_id, content=content, metadata=metadata or {})],
        )
        return ids[0] if ids else doc_id

    def delete(self, doc_ids: list[str], collection: str = DEFAULT_KNOWLEDGE_COLLECTION) -> bool:
        """删除文档。"""
        return self._store.delete_documents(collection, doc_ids)

    def search(
        self,
        query: str,
        n_results: int = 5,
        collection: str = DEFAULT_KNOWLEDGE_COLLECTION,
        where: Optional[dict] = None,
        query_embedding: Optional[list[float]] = None,
    ) -> list[dict[str, Any]]:
        """相似度检索。"""
        return self._store.query(
            collection,
            query_texts=None if query_embedding else [query],
            n_results=n_results,
            where=where,
            query_embeddings=[query_embedding] if query_embedding else None,
        )

    def delete_collection(self, collection: str) -> bool:
        """删除向量集合。"""
        return self._store.delete_collection(collection)

    def health_check(self) -> bool:
        """健康检查。"""
        return self._store.health_check()
