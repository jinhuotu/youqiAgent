"""PDF 文本抽取。"""

from collections.abc import Iterator
from pathlib import Path

from pypdf import PdfReader

from app.core.exceptions import BusinessError
from app.services.parsers.cleaning import clean_extracted_text


def iter_pdf_page_texts(path: Path) -> Iterator[str]:
    """逐页抽取 PDF 文本，避免先拼成超大字符串再处理。"""
    try:
        reader = PdfReader(str(path))
        yielded = False
        for page in reader.pages:
            raw = page.extract_text() or ""
            text = clean_extracted_text(raw)
            if text:
                yielded = True
                yield text
        if not yielded:
            raise BusinessError("PDF 未提取到文本（可能是扫描件，本期不支持 OCR）")
    except BusinessError:
        raise
    except Exception as e:
        raise BusinessError(f"PDF 解析失败: {e}") from e


def extract_pdf_text(path: Path) -> str:
    """从 PDF 抽取全文（兼容旧调用；内部仍逐页抽取后拼接）。"""
    pages = list(iter_pdf_page_texts(path))
    return "\n\n".join(pages)
