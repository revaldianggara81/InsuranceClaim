"""
KB Loader — Read knowledge base files from local folder.
Config dibaca dari environment variables (.env).
"""
import os
from pathlib import Path
from typing import Tuple

KB_TEXT_EXTS = (".txt", ".json", ".md", ".csv", ".yaml", ".yml", ".pdf")


def _extract_pdf_pages(pdf_bytes: bytes, max_pages: int = 15) -> list:
    try:
        import io
        from pypdf import PdfReader
        reader = PdfReader(io.BytesIO(pdf_bytes))
        pages = []
        for i, page in enumerate(reader.pages[:max_pages], start=1):
            text = (page.extract_text() or "").strip()
            if text:
                pages.append((i, text))
        return pages
    except Exception as e:
        return [(0, f"[PDF read error: {e}]")]


def _extract_pdf_text(pdf_bytes: bytes, max_pages: int = 15) -> str:
    pages = _extract_pdf_pages(pdf_bytes, max_pages)
    return "\n\n".join(f"[Page {p}]\n{text}" for p, text in pages)


def load_kb_content(
    max_size_bytes: int = 60_000,
) -> Tuple[str, str]:
    """
    Load KB content from local folder (config from env).
    Returns (kb_text, pdf_par_url) tuple.
    """
    kb_local_path = os.getenv("KB_LOCAL_PATH", "")
    pdf_url       = os.getenv("KB_PDF_PAR_URL", "")

    if not kb_local_path:
        return "[Knowledge base unavailable: KB_LOCAL_PATH not set]", pdf_url

    kb_dir = Path(kb_local_path)
    if not kb_dir.exists():
        return f"[Knowledge base unavailable: folder '{kb_local_path}' not found]", pdf_url

    kb_parts    = []
    total_bytes = 0

    for file_path in sorted(kb_dir.iterdir()):
        if not file_path.is_file():
            continue
        if not any(file_path.name.lower().endswith(ext) for ext in KB_TEXT_EXTS):
            continue
        try:
            raw = file_path.read_bytes()
            content = (
                _extract_pdf_text(raw)
                if file_path.name.lower().endswith(".pdf")
                else raw.decode("utf-8", errors="ignore")
            )
            section = f"=== {file_path.name} ===\n{content}"
            kb_parts.append(section)
            total_bytes += len(section)
            if total_bytes >= max_size_bytes:
                kb_parts.append("[...KB truncated due to size limit...]")
                break
        except Exception as e:
            kb_parts.append(f"=== {file_path.name} === [read error: {str(e)}]")

    if not kb_parts:
        return "[Knowledge base is empty or contains no readable files]", pdf_url

    return "\n\n".join(kb_parts), pdf_url
