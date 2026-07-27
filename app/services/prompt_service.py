"""提示词模板管理业务服务。"""

from typing import Optional

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.context import get_current_role, get_current_user_id
from app.core.exceptions import ForbiddenError, NotFoundError
from app.core.logger import get_logger
from app.db.mysql.models.prompt_template import PromptTemplate, TemplateScope
from app.schemas.request.prompt import PromptCreateRequest, PromptUpdateRequest
from app.schemas.response.prompt import PromptResponse
from app.utils.template import render_template

log = get_logger("services.prompt")


class PromptService:
    """提示词模板业务逻辑。"""

    def __init__(self, db: Session) -> None:
        self.db = db
        self.settings = get_settings()

    def _to_response(self, row: PromptTemplate) -> PromptResponse:
        return PromptResponse.model_validate(row)

    def list_prompts(self) -> list[PromptResponse]:
        """获取当前用户可用模板：公共 + 自己的私有。"""
        user_id = get_current_user_id()
        stmt = (
            select(PromptTemplate)
            .where(
                or_(
                    PromptTemplate.scope == TemplateScope.PUBLIC,
                    (PromptTemplate.scope == TemplateScope.PRIVATE)
                    & (PromptTemplate.user_id == user_id),
                )
            )
            .order_by(PromptTemplate.id.desc())
        )
        rows = self.db.scalars(stmt).all()
        return [self._to_response(r) for r in rows]

    def get_prompt(self, prompt_id: int) -> PromptResponse:
        """获取模板详情。"""
        row = self._get_accessible_row(prompt_id)
        return self._to_response(row)

    def get_rendered_content(
        self,
        prompt_id: int,
        variables: Optional[dict] = None,
    ) -> str:
        """获取并渲染模板内容（供对话注入 system prompt）。"""
        row = self._get_accessible_row(prompt_id)
        return render_template(row.content, variables)

    def create_prompt(self, req: PromptCreateRequest) -> PromptResponse:
        """新增模板。"""
        user_id = get_current_user_id()
        role = get_current_role()

        if req.scope == TemplateScope.PUBLIC:
            if not self.settings.enable_admin_role or role != "admin":
                raise ForbiddenError("仅管理员可创建公共模板")
            owner_id = "0"
        else:
            owner_id = user_id

        row = PromptTemplate(
            name=req.name,
            content=req.content,
            model_type=req.model_type,
            scope=req.scope,
            user_id=owner_id,
            description=req.description,
        )
        self.db.add(row)
        self.db.commit()
        self.db.refresh(row)
        log.info(f"创建提示词模板: id={row.id}, name={row.name}")
        return self._to_response(row)

    def update_prompt(self, prompt_id: int, req: PromptUpdateRequest) -> PromptResponse:
        """编辑模板。"""
        row = self._get_editable_row(prompt_id)
        data = req.model_dump(exclude_unset=True)
        if "scope" in data and data["scope"] == TemplateScope.PUBLIC:
            if not self.settings.enable_admin_role or get_current_role() != "admin":
                raise ForbiddenError("仅管理员可将模板设为公共")
            data["user_id"] = "0"
        for key, value in data.items():
            setattr(row, key, value)
        self.db.commit()
        self.db.refresh(row)
        log.info(f"更新提示词模板: id={row.id}")
        return self._to_response(row)

    def delete_prompt(self, prompt_id: int) -> None:
        """删除模板。"""
        row = self._get_editable_row(prompt_id)
        self.db.delete(row)
        self.db.commit()
        log.info(f"删除提示词模板: id={prompt_id}")

    def _get_accessible_row(self, prompt_id: int) -> PromptTemplate:
        user_id = get_current_user_id()
        row = self.db.get(PromptTemplate, prompt_id)
        if row is None:
            raise NotFoundError("提示词模板不存在")
        if row.scope == TemplateScope.PRIVATE and row.user_id != user_id:
            raise NotFoundError("提示词模板不存在")
        return row

    def _get_editable_row(self, prompt_id: int) -> PromptTemplate:
        user_id = get_current_user_id()
        role = get_current_role()
        row = self.db.get(PromptTemplate, prompt_id)
        if row is None:
            raise NotFoundError("提示词模板不存在")
        if row.scope == TemplateScope.PUBLIC:
            if not self.settings.enable_admin_role or role != "admin":
                raise ForbiddenError("仅管理员可管理公共模板")
        elif row.user_id != user_id:
            raise ForbiddenError("无权操作该私有模板")
        return row
