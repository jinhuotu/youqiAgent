"""PDF 文本抽取。"""

from pathlib import Path

from pypdf import PdfReader

from app.core.exceptions import BusinessError
from app.services.parsers.cleaning import clean_extracted_text


def extract_pdf_text(path: Path) -> str:
    """从 PDF 抽取文本（不含 OCR）。"""
    try:
        reader = PdfReader(str(path))
        pages: list[str] = []
        for page in reader.pages:
            pages.append(page.extract_text() or "")
        text = clean_extracted_text("\n\n".join(pages))
        if not text:
            raise BusinessError("PDF 未提取到文本（可能是扫描件，本期不支持 OCR）")
        return text
    except BusinessError:
        raise
    except Exception as e:
        raise BusinessError(f"PDF 解析失败: {e}") from e
