"""内部接口路由聚合。"""

from fastapi import APIRouter

from app.api.v1.internal import chat, conversation, knowledge, mcp, model, prompt, system

router = APIRouter(prefix="/api/v1/internal")

router.include_router(model.router, prefix="/models", tags=["模型管理"])
router.include_router(prompt.router, prefix="/prompts", tags=["提示词模板"])
router.include_router(conversation.router, prefix="/conversations", tags=["会话管理"])
router.include_router(chat.router, prefix="/chat", tags=["对话"])
router.include_router(knowledge.router, prefix="/knowledge-bases", tags=["知识库"])
router.include_router(mcp.router, prefix="/mcp-servers", tags=["MCP管理"])
router.include_router(system.router, prefix="/system", tags=["系统信息"])
