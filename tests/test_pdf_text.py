"""Unit tests for PDF text extraction (pure: bytes in, dict out)."""

import pytest

from salesforce_mcp.pdf_text import (
    PdfReadError,
    extract_pdf_text,
    format_pdf_pages,
    is_pdf,
)
from tests.pdf_fixtures import pdf_bytes


def test_is_pdf_by_extension_or_magic_bytes():
    assert is_pdf("PDF", b"")
    assert is_pdf("", b"%PDF-1.7 ...")
    assert is_pdf("docx", b"%PDF-1.7 ...")
    assert not is_pdf("txt", b"hello")


def test_extracts_all_pages():
    result = extract_pdf_text(pdf_bytes(["alpha", "beta", "gamma"]))
    assert result["totalPages"] == 3
    assert [p["page"] for p in result["pages"]] == [1, 2, 3]
    assert [p["text"].strip() for p in result["pages"]] == ["alpha", "beta", "gamma"]
    assert result["truncated"] is False
    assert result["nextPage"] is None
    assert result["stopReason"] == "complete"
    assert result["warnings"] == []


def test_format_pdf_pages_adds_separators():
    pages = [{"page": 2, "text": "beta"}, {"page": 3, "text": "gamma"}]
    assert format_pdf_pages(pages, 3) == (
        "--- Page 2 of 3 ---\nbeta\n\n--- Page 3 of 3 ---\ngamma"
    )


def test_start_page_continues_from_there():
    result = extract_pdf_text(pdf_bytes(["alpha", "beta", "gamma"]), start_page=2)
    assert [p["page"] for p in result["pages"]] == [2, 3]
    assert result["stopReason"] == "complete"


@pytest.mark.parametrize("start_page", [0, -1, 4])
def test_start_page_out_of_range_raises(start_page):
    with pytest.raises(PdfReadError) as exc:
        extract_pdf_text(pdf_bytes(["alpha", "beta", "gamma"]), start_page=start_page)
    assert exc.value.code == "invalid_start_page"


def test_page_over_budget_is_cut_mid_page():
    result = extract_pdf_text(pdf_bytes(["a" * 30, "b" * 30, "c" * 30]), char_limit=40)
    assert [p["page"] for p in result["pages"]] == [1, 2]
    assert result["pages"][0]["truncated"] is False
    assert result["pages"][1]["truncated"] is True
    assert sum(len(p["text"]) for p in result["pages"]) == 40
    assert result["truncated"] is True
    assert result["stopReason"] == "character_limit"
    assert result["nextPage"] == 3
    assert "Page 2 exceeds the character limit" in result["warnings"][0]
    assert result["warnings"][-1].endswith("Call again with start_page: 3.")


def test_cut_on_last_page_has_no_next_page():
    result = extract_pdf_text(pdf_bytes(["a" * 30]), char_limit=10)
    assert result["pages"][0]["truncated"] is True
    assert result["truncated"] is True
    assert result["nextPage"] is None
    assert result["stopReason"] == "character_limit"


def test_budget_hit_exactly_on_page_boundary_loses_no_text():
    first = extract_pdf_text(pdf_bytes(["a" * 30, "b" * 30]))["pages"][0]["text"]
    result = extract_pdf_text(pdf_bytes(["a" * 30, "b" * 30]), char_limit=len(first))
    assert [p["page"] for p in result["pages"]] == [1]
    assert result["pages"][0]["truncated"] is False
    assert result["truncated"] is True
    assert result["nextPage"] == 2


def test_page_limit_stops_and_continues():
    result = extract_pdf_text(pdf_bytes(["one", "two", "three"]), max_pages=2)
    assert [p["page"] for p in result["pages"]] == [1, 2]
    assert result["stopReason"] == "page_limit"
    assert result["nextPage"] == 3
    assert "Stopped at page 2 of 3 (page limit)" in result["warnings"][-1]


def test_time_limit_is_checked_between_pages():
    ticks = iter([0.0, 0.0, 11.0])
    result = extract_pdf_text(
        pdf_bytes(["one", "two", "three"]), time_limit_s=10.0, now=lambda: next(ticks)
    )
    assert [p["page"] for p in result["pages"]] == [1]
    assert result["stopReason"] == "time_limit"
    assert result["nextPage"] == 2


def test_has_images_flags_direct_and_form_wrapped_images():
    data = pdf_bytes(["text", "text", "text"], image_pages={2}, form_image_pages={3})
    result = extract_pdf_text(data)
    assert [p["hasImages"] for p in result["pages"]] == [False, True, True]
    assert result["warnings"] == ["Pages 2, 3 contain images that were not parsed."]


def test_image_only_page_gets_ocr_warning():
    result = extract_pdf_text(pdf_bytes(["text", ""], image_pages={2}))
    assert result["warnings"] == [
        "Page 2 contains images that were not parsed.",
        "Page 2 contains no extractable text. OCR is not supported.",
    ]


def test_blank_page_without_images_is_not_flagged():
    result = extract_pdf_text(pdf_bytes(["text", ""]))
    assert result["pages"][1]["hasImages"] is False
    assert result["warnings"] == []


def test_fully_scanned_pdf_returns_warnings_not_error():
    result = extract_pdf_text(pdf_bytes(["", ""], image_pages={1, 2}))
    assert result["stopReason"] == "complete"
    assert all(not p["text"].strip() for p in result["pages"])
    assert "OCR is not supported" in result["warnings"][-1]


def test_owner_only_password_opens():
    result = extract_pdf_text(pdf_bytes(["secret"], owner_password="owner"))
    assert result["pages"][0]["text"].strip() == "secret"


def test_user_password_rejected():
    with pytest.raises(PdfReadError) as exc:
        extract_pdf_text(pdf_bytes(["secret"], user_password="user", owner_password="owner"))
    assert exc.value.code == "password_protected"


def test_corrupt_pdf_raises():
    with pytest.raises(PdfReadError) as exc:
        extract_pdf_text(b"%PDF-1.7\nthis is not really a pdf")
    assert exc.value.code == "invalid_pdf"
