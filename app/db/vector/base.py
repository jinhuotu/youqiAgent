"""向量数据库操作抽象基类。

定义统一的增删查接口，本期预留知识库集合，暂不绑定具体业务。
"""

from abc import ABC, abstractmethod
from typing import Any, Optional


class VectorDocument:
    """向量文档数据结构。"""

    def __init__(
        self,
        doc_id: str,
        content: str,
        metadata: Optional[dict[str, Any]] = None,
        embedding: Optional[list[float]] = None,
    ) -> None:
        self.doc_id = doc_id
        self.content = content
        self.metadata = metadata or {}
        self.embedding = embedding


class BaseVectorStore(ABC):
    """向量数据库抽象基类。

    所有实现类必须实现集合管理与文档增删查接口。
    """

    @abstractmethod
    def ensure_collection(self, collection_name: str, metadata: Optional[dict] = None) -> None:
        """确保集合存在，不存在则创建。

        Args:
            collection_name: 集合名称
            metadata: 集合元数据
        """

    @abstractmethod
    def add_documents(
        self,
        collection_name: str,
        documents: list[VectorDocument],
    ) -> list[str]:
        """向集合添加文档。

        Args:
            collection_name: 集合名称
            documents: 文档列表

        Returns:
            成功写入的文档 ID 列表
        """

    @abstractmethod
    def delete_documents(self, collection_name: str, doc_ids: list[str]) -> bool:
        """按 ID 删除文档。

        Args:
            collection_name: 集合名称
            doc_ids: 文档 ID 列表

        Returns:
            是否删除成功
        """

    @abstractmethod
    def query(
        self,
        collection_name: str,
        query_texts: list[str] | None = None,
        n_results: int = 5,
        where: Optional[dict] = None,
        query_embeddings: list[list[float]] | None = None,
    ) -> list[dict[str, Any]]:
        """相似度检索。

        Args:
            collection_name: 集合名称
            query_texts: 查询文本列表（与 query_embeddings 二选一）
            n_results: 返回条数
            where: 元数据过滤条件
            query_embeddings: 查询向量列表（与 query_texts 二选一）

        Returns:
            检索结果列表
        """

    @abstractmethod
    def get_by_ids(
        self,
        collection_name: str,
        doc_ids: list[str],
    ) -> list[dict[str, Any]]:
        """按 ID 批量查询文档。"""

    @abstractmethod
    def health_check(self) -> bool:
        """健康检查：向量库是否可用。"""

    @abstractmethod
    def list_collections(self) -> list[str]:
        """列出所有集合名称。"""

    @abstractmethod
    def delete_collection(self, collection_name: str) -> bool:
        """删除整个集合。"""
