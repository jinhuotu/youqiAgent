"""基于 ChromaDB 的向量数据库实现。

支持本地持久化存储，路径由 CHROMA_PERSIST_PATH 配置。
"""

from typing import Any, Optional

from app.core.config import get_settings
from app.core.logger import get_logger
from app.db.vector.base import BaseVectorStore, VectorDocument

log = get_logger("db.vector.chroma")


class ChromaVectorStore(BaseVectorStore):
    """ChromaDB 向量存储实现。"""

    def __init__(self, persist_path: Optional[str] = None) -> None:
        """初始化 Chroma 客户端。

        Args:
            persist_path: 持久化目录，默认读取配置
        """
        self._persist_path = persist_path or get_settings().chroma_persist_path
        self._client = None
        self._init_client()

    def _init_client(self) -> None:
        """懒加载创建 PersistentClient。"""
        try:
            import chromadb
            from chromadb.config import Settings as ChromaSettings

            self._client = chromadb.PersistentClient(
                path=self._persist_path,
                settings=ChromaSettings(anonymized_telemetry=False),
            )
            log.info(f"Chroma 客户端已初始化，路径={self._persist_path}")
        except Exception as e:
            log.error(f"Chroma 初始化失败: {e}")
            self._client = None

    def _get_collection(self, collection_name: str, metadata: Optional[dict] = None):
        """获取或创建集合。"""
        if self._client is None:
            raise RuntimeError("Chroma 客户端未初始化")
        return self._client.get_or_create_collection(
            name=collection_name,
            metadata=metadata or {"description": "knowledge_base_reserved"},
        )

    def ensure_collection(self, collection_name: str, metadata: Optional[dict] = None) -> None:
        """确保集合存在。"""
        self._get_collection(collection_name, metadata)
        log.info(f"确保集合存在: {collection_name}")

    def add_documents(
        self,
        collection_name: str,
        documents: list[VectorDocument],
    ) -> list[str]:
        """添加文档到指定集合。"""
        if not documents:
            return []
        collection = self._get_collection(collection_name)
        ids = [d.doc_id for d in documents]
        collection.add(
            ids=ids,
            documents=[d.content for d in documents],
            metadatas=[d.metadata for d in documents],
            embeddings=[d.embedding for d in documents] if documents[0].embedding else None,
        )
        log.info(f"向集合 {collection_name} 写入 {len(ids)} 条文档")
        return ids

    def delete_documents(self, collection_name: str, doc_ids: list[str]) -> bool:
        """按 ID 删除文档。"""
        try:
            collection = self._get_collection(collection_name)
            collection.delete(ids=doc_ids)
            log.info(f"从集合 {collection_name} 删除 {len(doc_ids)} 条文档")
            return True
        except Exception as e:
            log.warning(f"删除文档失败: {e}")
            return False

    def query(
        self,
        collection_name: str,
        query_texts: list[str] | None = None,
        n_results: int = 5,
        where: Optional[dict] = None,
        query_embeddings: list[list[float]] | None = None,
    ) -> list[dict[str, Any]]:
        """相似度检索。"""
        collection = self._get_collection(collection_name)
        kwargs: dict[str, Any] = {"n_results": n_results}
        if query_embeddings:
            kwargs["query_embeddings"] = query_embeddings
        elif query_texts:
            kwargs["query_texts"] = query_texts
        else:
            raise ValueError("query_texts 与 query_embeddings 不能同时为空")
        if where:
            kwargs["where"] = where
        results = collection.query(**kwargs)
        # 将 Chroma 返回结构扁平化为列表
        output: list[dict[str, Any]] = []
        ids_list = results.get("ids") or [[]]
        docs_list = results.get("documents") or [[]]
        metas_list = results.get("metadatas") or [[]]
        dists_list = results.get("distances") or [[]]
        for i, doc_id in enumerate(ids_list[0] if ids_list else []):
            output.append(
                {
                    "id": doc_id,
                    "content": docs_list[0][i] if docs_list and docs_list[0] else "",
                    "metadata": metas_list[0][i] if metas_list and metas_list[0] else {},
                    "distance": dists_list[0][i] if dists_list and dists_list[0] else None,
                }
            )
        return output

    def get_by_ids(
        self,
        collection_name: str,
        doc_ids: list[str],
    ) -> list[dict[str, Any]]:
        """按 ID 批量查询。"""
        collection = self._get_collection(collection_name)
        results = collection.get(ids=doc_ids)
        output: list[dict[str, Any]] = []
        for i, doc_id in enumerate(results.get("ids") or []):
            docs = results.get("documents") or []
            metas = results.get("metadatas") or []
            output.append(
                {
                    "id": doc_id,
                    "content": docs[i] if i < len(docs) else "",
                    "metadata": metas[i] if i < len(metas) else {},
                }
            )
        return output

    def health_check(self) -> bool:
        """健康检查。"""
        try:
            if self._client is None:
                self._init_client()
            if self._client is None:
                return False
            self._client.heartbeat()
            return True
        except Exception as e:
            log.warning(f"Chroma 健康检查失败: {e}")
            return False

    def list_collections(self) -> list[str]:
        """列出所有集合。"""
        if self._client is None:
            return []
        return [c.name for c in self._client.list_collections()]

    def delete_collection(self, collection_name: str) -> bool:
        """删除集合。"""
        try:
            if self._client is None:
                return False
            self._client.delete_collection(collection_name)
            log.info(f"已删除集合: {collection_name}")
            return True
        except Exception as e:
            log.warning(f"删除集合失败: {collection_name}, error={e}")
            return False


# 全局单例
_vector_store: Optional[ChromaVectorStore] = None


def get_vector_store() -> ChromaVectorStore:
    """获取全局向量存储单例。"""
    global _vector_store
    if _vector_store is None:
        _vector_store = ChromaVectorStore()
    return _vector_store
