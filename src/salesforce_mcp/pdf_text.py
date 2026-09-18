"""PDF text extraction for download_file's read mode (pypdf, no OCR)."""

import io
import time
from collections.abc import Callable

from pypdf import PdfReader
from pypdf.errors import PyPdfError

# Fixed per-call limits: server invariants, deliberately not env-configurable.
CHAR_LIMIT = 100_000
TIME_LIMIT_S = 10.0
MAX_PAGES_PER_CALL = 200
# Form XObjects can nest (and, in malformed files, cycle); stop looking here.
_MAX_XOBJECT_DEPTH = 3


class PdfReadError(ValueError):
    """A PDF could not be read. `code` is one of: invalid_start_page,
    password_protected, invalid_pdf, parse_failed."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def is_pdf(extension: str, data: bytes) -> bool:
    """Extensions in Salesforce can be missing or wrong; the magic bytes aren't."""
    return extension.lower() == "pdf" or data.startswith(b"%PDF-")


def format_pdf_pages(pages: list[dict], total_pages: int) -> str:
    """Join page text in page order, each page preceded by a `--- Page N of M ---` line."""
    return "\n\n".join(
        f"--- Page {page['page']} of {total_pages} ---\n{page['text']}" for page in pages
    )


def _has_images(resources, depth: int = 0) -> bool:
    """Check resources for image XObjects without decoding them, recursing into
    Form XObjects (scanners often wrap the page image in one). Inline images
    (BI operators in the content stream) are not seen."""
    if resources is None or depth > _MAX_XOBJECT_DEPTH:
        return False
    xobjects = resources.get_object().get("/XObject")
    if xobjects is None:
        return False
    for ref in xobjects.get_object().values():
        xobject = ref.get_object()
        subtype = xobject.get("/Subtype")
        if subtype == "/Image":
            return True
        if subtype == "/Form" and _has_images(xobject.get("/Resources"), depth + 1):
            return True
    return False


def _page_has_images(page) -> bool:
    # Best-effort: a malformed resource tree reads as "no images" rather than
    # failing the whole extraction.
    try:
        return _has_images(page.get("/Resources"))
    except (PyPdfError, AttributeError, KeyError, TypeError, ValueError):
        return False


def _page_list(pages: list[int]) -> str:
    if len(pages) == 1:
        return f"Page {pages[0]} contains"
    return f"Pages {', '.join(map(str, pages))} contain"


def _open(data: bytes) -> PdfReader:
    try:
        reader = PdfReader(io.BytesIO(data))
        if reader.is_encrypted and not reader.decrypt(""):
            # Owner-locked files open with the empty user password; anything
            # stronger is unreadable without credentials.
            raise PdfReadError(
                "password_protected",
                "PDF is password-protected. Remove the password before reading it.",
            )
        len(reader.pages)  # force the page tree to parse
    except PdfReadError:
        raise
    except Exception as e:
        raise PdfReadError("invalid_pdf", "The file is not a valid, readable PDF.") from e
    return reader


def extract_pdf_text(
    data: bytes,
    *,
    start_page: int = 1,
    char_limit: int = CHAR_LIMIT,
    time_limit_s: float = TIME_LIMIT_S,
    max_pages: int = MAX_PAGES_PER_CALL,
    now: Callable[[], float] = time.monotonic,
) -> dict:
    """Extract PDF text one page at a time, starting at `start_page`.

    The time limit is cooperative: it is checked between pages and cannot
    interrupt one pathological page. Returns `pages` (page, text, truncated,
    hasImages) plus totalPages, truncated, nextPage, stopReason, warnings.
    """
    if start_page < 1:
        raise PdfReadError("invalid_start_page", "start_page must be a positive integer.")

    started_at = now()
    reader = _open(data)
    total_pages = len(reader.pages)
    if start_page > total_pages:
        raise PdfReadError(
            "invalid_start_page",
            f"start_page {start_page} exceeds the PDF's {total_pages} "
            f"page{'' if total_pages == 1 else 's'}.",
        )

    pages: list[dict] = []
    warnings: list[str] = []
    pages_with_images: list[int] = []
    image_only_pages: list[int] = []
    character_count = 0
    stop_reason = "complete"
    next_page = None

    for number in range(start_page, total_pages + 1):
        if len(pages) >= max_pages:
            stop_reason, next_page = "page_limit", number
            break
        if now() - started_at >= time_limit_s:
            stop_reason, next_page = "time_limit", number
            break

        page = reader.pages[number - 1]
        try:
            full_text = page.extract_text() or ""
        except Exception as e:
            raise PdfReadError(
                "parse_failed", f"PDF text extraction failed on page {number}: {e}"
            ) from e
        has_images = _page_has_images(page)
        remaining = char_limit - character_count
        page_truncated = len(full_text) > remaining
        text = full_text[:remaining] if page_truncated else full_text

        pages.append(
            {"page": number, "text": text, "truncated": page_truncated, "hasImages": has_images}
        )
        character_count += len(text)
        if has_images:
            pages_with_images.append(number)
            if not full_text.strip():
                image_only_pages.append(number)

        if page_truncated:
            warnings.append(
                f"Page {number} exceeds the character limit; its text was cut "
                "mid-page and the remainder is not retrievable."
            )
            stop_reason = "character_limit"
            next_page = number + 1 if number < total_pages else None
            break
        if number < total_pages and character_count >= char_limit:
            stop_reason, next_page = "character_limit", number + 1
            break

    if pages_with_images:
        warnings.append(f"{_page_list(pages_with_images)} images that were not parsed.")
    if image_only_pages:
        warnings.append(
            f"{_page_list(image_only_pages)} no extractable text. OCR is not supported."
        )
    if next_page is not None:
        stopped = f"Stopped at page {pages[-1]['page']}" if pages else f"Stopped before page {next_page}"
        warnings.append(
            f"{stopped} of {total_pages} ({stop_reason.replace('_', ' ')}). "
            f"Call again with start_page: {next_page}."
        )

    return {
        "totalPages": total_pages,
        "pages": pages,
        "truncated": stop_reason != "complete" or any(p["truncated"] for p in pages),
        "nextPage": next_page,
        "stopReason": stop_reason,
        "warnings": warnings,
    }
