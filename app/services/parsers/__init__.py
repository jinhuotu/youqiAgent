"""文档解析统一入口。"""

from pathlib import Path

from app.core.exceptions import ParamError
from app.services.parsers.docx_parser import extract_docx_text
from app.services.parsers.pdf_parser import extract_pdf_text
from app.services.parsers.xlsx_parser import extract_xlsx_text


def extract_text(path: Path | str, ext: str) -> str:
    """按扩展名抽取文本。

    Args:
        path: 本地文件路径
        ext: 扩展名（不含点），如 pdf/docx/xlsx
    """
    file_path = Path(path)
    key = (ext or "").lower().lstrip(".")
    if key == "pdf":
        return extract_pdf_text(file_path)
    if key == "docx":
        return extract_docx_text(file_path)
    if key == "xlsx":
        return extract_xlsx_text(file_path)
    raise ParamError(f"不支持的解析类型: {ext}")
