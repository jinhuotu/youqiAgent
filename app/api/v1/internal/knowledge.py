"""知识库内部接口。"""

from fastapi import APIRouter, Depends, File, UploadFile
from sqlalchemy.orm import Session

from app.core.logger import get_logger
from app.db.mysql.models.knowledge import DocumentParseStatus
from app.db.mysql.session import get_db
from app.schemas.request.knowledge import (
    KnowledgeBaseCreateRequest,
    KnowledgeBaseUpdateRequest,
    KnowledgeDocumentCreateRequest,
    KnowledgeEvalRequest,
    KnowledgeSearchRequest,
)
from app.schemas.response.common import ApiResponse
from app.schemas.response.knowledge import (
    KnowledgeBaseResponse,
    KnowledgeDocumentResponse,
    KnowledgeEvalResponse,
    KnowledgeSearchResponse,
)
from app.services.kb_job_queue import enqueue_document_job
from app.services.knowledge_service import KnowledgeService

router = APIRouter()
log = get_logger("api.knowledge")


@router.get(
    "",
    response_model=ApiResponse[list[KnowledgeBaseResponse]],
    summary="知识库列表",
)
def list_knowledge_bases(db: Session = Depends(get_db)) -> ApiResponse[list[KnowledgeBaseResponse]]:
    return ApiResponse.ok(KnowledgeService(db).list_knowledge_bases())


@router.post(
    "",
    response_model=ApiResponse[KnowledgeBaseResponse],
    summary="创建知识库",
)
def create_knowledge_base(
    req: KnowledgeBaseCreateRequest,
    db: Session = Depends(get_db),
) -> ApiResponse[KnowledgeBaseResponse]:
    return ApiResponse.ok(KnowledgeService(db).create_knowledge_base(req), message="创建成功")


@router.get(
    "/{kb_id}",
    response_model=ApiResponse[KnowledgeBaseResponse],
    summary="知识库详情",
)
def get_knowledge_base(
    kb_id: int,
    db: Session = Depends(get_db),
) -> ApiResponse[KnowledgeBaseResponse]:
    return ApiResponse.ok(KnowledgeService(db).get_knowledge_base(kb_id))


@router.put(
    "/{kb_id}",
    response_model=ApiResponse[KnowledgeBaseResponse],
    summary="更新知识库",
)
def update_knowledge_base(
    kb_id: int,
    req: KnowledgeBaseUpdateRequest,
    db: Session = Depends(get_db),
) -> ApiResponse[KnowledgeBaseResponse]:
    svc = KnowledgeService(db)
    # 变更前记录 Embedding，用于提示是否触发重建
    before = svc.get_knowledge_base(kb_id)
    data = svc.update_knowledge_base(kb_id, req)
    message = "更新成功"
    if (
        "embedding_model_id" in req.model_dump(exclude_unset=True)
        and before.embedding_model_id != data.embedding_model_id
    ):
        message = (
            "更新成功：Embedding 模型已变更，旧向量已清空，"
            "相关文档已重新排队向量化，请在文档列表查看进度"
        )
    return ApiResponse.ok(data, message=message)


@router.delete(
    "/{kb_id}",
    response_model=ApiResponse[None],
    summary="删除知识库",
)
def delete_knowledge_base(
    kb_id: int,
    db: Session = Depends(get_db),
) -> ApiResponse[None]:
    KnowledgeService(db).delete_knowledge_base(kb_id)
    return ApiResponse.ok(message="删除成功")


@router.get(
    "/{kb_id}/documents",
    response_model=ApiResponse[list[KnowledgeDocumentResponse]],
    summary="文档列表",
)
def list_documents(
    kb_id: int,
    db: Session = Depends(get_db),
) -> ApiResponse[list[KnowledgeDocumentResponse]]:
    return ApiResponse.ok(KnowledgeService(db).list_documents(kb_id))


@router.post(
    "/{kb_id}/documents",
    response_model=ApiResponse[KnowledgeDocumentResponse],
    summary="录入文本文档",
)
def add_document(
    kb_id: int,
    req: KnowledgeDocumentCreateRequest,
    db: Session = Depends(get_db),
) -> ApiResponse[KnowledgeDocumentResponse]:
    return ApiResponse.ok(
        KnowledgeService(db).add_document(kb_id, req),
        message="录入成功",
    )


@router.post(
    "/{kb_id}/documents/upload",
    response_model=ApiResponse[list[KnowledgeDocumentResponse]],
    summary="多文件上传入库（异步解析）",
)
async def upload_documents(
    kb_id: int,
    files: list[UploadFile] = File(..., description="pdf/docx/xlsx 多文件"),
    db: Session = Depends(get_db),
) -> ApiResponse[list[KnowledgeDocumentResponse]]:
    """先落盘并立即返回；解析/切分/向量化由 Redis 队列异步执行，前端轮询文档状态。"""
    data = await KnowledgeService(db).upload_documents(kb_id, files)
    for item in data:
        if item.parse_status == DocumentParseStatus.PROCESSING and item.file_path:
            enqueue_document_job(item.id)
    return ApiResponse.ok(data, message="文件已接收，后台处理中，请在列表查看进度")


@router.delete(
    "/{kb_id}/documents/{doc_id}",
    response_model=ApiResponse[None],
    summary="删除文档",
)
def delete_document(
    kb_id: int,
    doc_id: int,
    db: Session = Depends(get_db),
) -> ApiResponse[None]:
    KnowledgeService(db).delete_document(kb_id, doc_id)
    return ApiResponse.ok(message="删除成功")


@router.post(
    "/{kb_id}/search",
    response_model=ApiResponse[KnowledgeSearchResponse],
    summary="知识库试检索",
)
def search_knowledge(
    kb_id: int,
    req: KnowledgeSearchRequest,
    db: Session = Depends(get_db),
) -> ApiResponse[KnowledgeSearchResponse]:
    return ApiResponse.ok(KnowledgeService(db).search(kb_id, req))


@router.post(
    "/{kb_id}/eval",
    response_model=ApiResponse[KnowledgeEvalResponse],
    summary="知识库语义检索评测（黄金集）",
)
def eval_knowledge(
    kb_id: int,
    req: KnowledgeEvalRequest,
    db: Session = Depends(get_db),
) -> ApiResponse[KnowledgeEvalResponse]:
    return ApiResponse.ok(KnowledgeService(db).evaluate_retrieval(kb_id, req))
