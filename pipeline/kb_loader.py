"""
KB Loader — Read knowledge base files from OCI Object Storage.
Config dibaca dari environment variables (.env).
"""
import os
import oci
from typing import Tuple


KB_TEXT_EXTS = (".txt", ".json", ".md", ".csv", ".yaml", ".yml", ".pdf")


def _get_cfg():
    return {
        "region":      os.getenv("KB_OCI_REGION",    "ap-singapore-1"),
        "namespace":   os.getenv("KB_OCI_NAMESPACE",  "oscjapac002"),
        "bucket":      os.getenv("KB_OCI_BUCKET",     "ClaimInsurance"),
        "prefix":      os.getenv("KB_OCI_PREFIX",     "Private_Car_Policy_Wording"),
        "pdf_par_url": os.getenv("KB_PDF_PAR_URL",    ""),
    }


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
    signer,
    max_size_bytes: int = 60_000,
) -> Tuple[str, str]:
    """
    Load KB content from OCI bucket (config from env).
    Returns (kb_text, pdf_par_url) tuple.
    """
    cfg = _get_cfg()
    client = oci.object_storage.ObjectStorageClient(
        config={"region": cfg["region"]},
        signer=signer,
    )

    try:
        response = client.list_objects(
            namespace_name=cfg["namespace"],
            bucket_name=cfg["bucket"],
            prefix=cfg["prefix"],
        )
    except Exception as e:
        return f"[Knowledge base unavailable: {str(e)}]", ""

    kb_parts = []
    pdf_url  = cfg["pdf_par_url"]  # static PAR URL from env
    total_bytes = 0

    for obj in response.data.objects:
        name = obj.name.lower()
        if not any(name.endswith(ext) for ext in KB_TEXT_EXTS):
            continue
        try:
            resp = client.get_object(
                namespace_name=cfg["namespace"],
                bucket_name=cfg["bucket"],
                object_name=obj.name,
            )
            raw = resp.data.content
            content = _extract_pdf_text(raw) if name.endswith(".pdf") else raw.decode("utf-8", errors="ignore")

            section = f"=== {obj.name} ===\n{content}"
            kb_parts.append(section)
            total_bytes += len(section)
            if total_bytes >= max_size_bytes:
                kb_parts.append("[...KB truncated due to size limit...]")
                break
        except Exception as e:
            kb_parts.append(f"=== {obj.name} === [read error: {str(e)}]")

    if not kb_parts:
        return "[Knowledge base is empty or contains no readable files]", ""

    return "\n\n".join(kb_parts), pdf_url
