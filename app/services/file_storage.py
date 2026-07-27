"""知识库上传文件本地存储。"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from pathlib import Path

from fastapi import UploadFile

from app.core.config import get_settings
from app.core.exceptions import BusinessError, ParamError
from app.core.logger import get_logger

log = get_logger("services.file_storage")

ALLOWED_EXTENSIONS = {"pdf", "docx", "xlsx"}


@dataclass
class SavedUpload:
    """落盘结果。"""

    relative_path: str
    absolute_path: Path
    original_name: str
    ext: str
    size: int


class FileStorageService:
    """本地上传文件存储。"""

    def __init__(self) -> None:
        self.settings = get_settings()
        self.root = Path(self.settings.upload_root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def _kb_dir(self, kb_id: int) -> Path:
        path = self.root / f"kb_{kb_id}"
        path.mkdir(parents=True, exist_ok=True)
        return path

    @staticmethod
    def _safe_filename(name: str) -> str:
        base = Path(name or "file").name
        base = re.sub(r"[^\w.\u4e00-\u9fff-]+", "_", base, flags=re.UNICODE)
        return base[:180] or "file"

    def validate_batch_count(self, count: int) -> None:
        max_n = self.settings.upload_max_files_per_request
        if count <= 0:
            raise ParamError("请至少上传一个文件")
        if count > max_n:
            raise ParamError(f"单次最多上传 {max_n} 个文件")

    async def save_upload(self, kb_id: int, upload: UploadFile) -> SavedUpload:
        """校验并保存单个上传文件。"""
        original = upload.filename or "unnamed"
        ext = Path(original).suffix.lower().lstrip(".")
        if ext not in ALLOWED_EXTENSIONS:
            raise ParamError(f"不支持的文件类型: .{ext}，仅支持 pdf/docx/xlsx")

        data = await upload.read()
        size = len(data)
        max_bytes = self.settings.upload_max_file_size_mb * 1024 * 1024
        if size <= 0:
            raise ParamError(f"文件为空: {original}")
        if size > max_bytes:
            raise ParamError(
                f"文件过大: {original}，上限 {self.settings.upload_max_file_size_mb}MB"
            )

        safe = self._safe_filename(original)
        stored_name = f"{uuid.uuid4().hex}_{safe}"
        abs_path = self._kb_dir(kb_id) / stored_name
        abs_path.write_bytes(data)
        rel = f"kb_{kb_id}/{stored_name}"
        log.info(f"文件已保存: kb_id={kb_id}, path={rel}, size={size}")
        return SavedUpload(
            relative_path=rel,
            absolute_path=abs_path,
            original_name=original,
            ext=ext,
            size=size,
        )

    def resolve_absolute(self, relative_path: str) -> Path:
        """将相对路径解析为绝对路径，并防止目录穿越。"""
        target = (self.root / relative_path).resolve()
        if not str(target).startswith(str(self.root)):
            raise BusinessError("非法文件路径")
        return target

    def delete_file(self, relative_path: str | None) -> None:
        """删除本地文件（忽略不存在）。"""
        if not relative_path:
            return
        try:
            path = self.resolve_absolute(relative_path)
            if path.is_file():
                path.unlink()
                log.info(f"已删除本地文件: {relative_path}")
        except Exception as e:
            log.warning(f"删除本地文件失败: {relative_path}, error={e}")
