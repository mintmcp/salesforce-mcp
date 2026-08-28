"""Unit tests for read_content_version_text (mocked, no live org)."""

import io
from unittest.mock import MagicMock

import pytest
from pypdf import PdfWriter
from pypdf.generic import DictionaryObject, NameObject, StreamObject

from salesforce_mcp.client import (
    SalesforceClient,
    _format_page_ranges,
    _parse_page_spec,
)


def _pdf_bytes(
    page_texts: list[str],
    user_password: str | None = None,
    owner_password: str | None = None,
) -> bytes:
    """Build a small real PDF where each entry in page_texts becomes one page.

    An empty-string entry produces a page with no text content (the scanned-
    image shape). pypdf has no text-drawing API, so the content stream is
    assembled by hand from a Helvetica show-text operator.
    """
    writer = PdfWriter()
    for text in page_texts:
        page = writer.add_blank_page(width=300, height=300)
        if text:
            font = DictionaryObject(
                {
                    NameObject("/Type"): NameObject("/Font"),
                    NameObject("/Subtype"): NameObject("/Type1"),
                    NameObject("/BaseFont"): NameObject("/Helvetica"),
                }
            )
            page[NameObject("/Resources")] = DictionaryObject(
                {NameObject("/Font"): DictionaryObject({NameObject("/F1"): font})}
            )
            stream = StreamObject()
            stream.set_data(f"BT /F1 12 Tf 40 150 Td ({text}) Tj ET".encode())
            page[NameObject("/Contents")] = writer._add_object(stream)
    if user_password is not None or owner_password is not None:
        writer.encrypt(
            user_password=user_password or "",
            owner_password=owner_password,
            algorithm="RC4-128",
        )
    buffer = io.BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


def _client_for(data: bytes, extension: str = "pdf", size: int | None = None):
    sf = MagicMock()
    sf.query.return_value = {
        "totalSize": 1,
        "records": [
            {
                "Id": "068000000000001",
                "Title": "report",
                "FileExtension": extension,
                "ContentSize": len(data) if size is None else size,
            }
        ],
    }
    resp = MagicMock()
    resp.__enter__.return_value = resp
    resp.iter_content.return_value = [data]
    sf._call_salesforce.return_value = resp
    client = SalesforceClient()
    client._sf = sf
    return client, sf


# --- page-spec helpers ---


def test_parse_page_spec_forms():
    assert _parse_page_spec("3", 10) == [3]
    assert _parse_page_spec("1-5", 10) == [1, 2, 3, 4, 5]
    assert _parse_page_spec("2,5-7", 10) == [2, 5, 6, 7]
    # Order preserved, duplicates dropped.
    assert _parse_page_spec("5,1-3,2", 10) == [5, 1, 2, 3]


def test_parse_page_spec_rejects_bad_specs():
    for bad in ["", "0", "abc", "3-1", "1-", "-2", "1,,2"]:
        with pytest.raises(ValueError):
            _parse_page_spec(bad, 10)


def test_parse_page_spec_rejects_out_of_range():
    with pytest.raises(ValueError, match="out of range"):
        _parse_page_spec("1-11", 10)


def test_format_page_ranges():
    assert _format_page_ranges([1]) == "1"
    assert _format_page_ranges([1, 2, 3]) == "1-3"
    assert _format_page_ranges([1, 2, 3, 5]) == "1-3,5"
    assert _format_page_ranges([2, 5, 6, 7]) == "2,5-7"


# --- PDF extraction ---


def test_read_pdf_extracts_all_pages():
    data = _pdf_bytes(["Hello page one", "Hello page two"])
    client, _ = _client_for(data)
    out = client.read_content_version_text("068000000000001", 10_000_000, 100_000)
    assert out["pageCount"] == 2
    assert out["pagesReturned"] == "1-2"
    assert out["mimeType"] == "application/pdf"
    assert out["truncated"] is False
    assert "Hello page one" in out["text"]
    assert "Hello page two" in out["text"]
    assert "--- page 1 ---" in out["text"]
    assert "--- page 2 ---" in out["text"]


def test_read_pdf_pages_spec_selects_pages():
    data = _pdf_bytes(["alpha", "bravo", "charlie"])
    client, _ = _client_for(data)
    out = client.read_content_version_text(
        "068000000000001", 10_000_000, 100_000, pages="1,3"
    )
    assert out["pagesReturned"] == "1,3"
    assert "alpha" in out["text"]
    assert "charlie" in out["text"]
    assert "bravo" not in out["text"]


def test_read_pdf_pages_out_of_range_raises():
    data = _pdf_bytes(["alpha"])
    client, _ = _client_for(data)
    with pytest.raises(ValueError, match="out of range"):
        client.read_content_version_text(
            "068000000000001", 10_000_000, 100_000, pages="2"
        )


def test_read_pdf_truncates_on_page_boundary():
    data = _pdf_bytes(["first page words", "second page words", "third page words"])
    client, _ = _client_for(data)
    out = client.read_content_version_text("068000000000001", 10_000_000, 40)
    assert out["truncated"] is True
    assert out["pageCount"] == 3
    # Only complete pages are returned; the page that didn't fit is the
    # continuation point and none of its text leaks into this response.
    assert out["pagesReturned"] == "1"
    assert out["truncatedAtPage"] == 2
    assert "first page words" in out["text"]
    assert "second" not in out["text"]
    assert "--- page 2 ---" not in out["text"]
    assert len(out["text"]) <= 40
    # Page 2 would fit in a fresh call, so continuation works — no dead-end note.
    assert "note" not in out


def test_read_pdf_first_page_over_limit_returns_empty_with_note():
    data = _pdf_bytes(["this page alone is bigger than the cap"])
    client, _ = _client_for(data)
    out = client.read_content_version_text("068000000000001", 10_000_000, 10)
    assert out["truncated"] is True
    assert out["truncatedAtPage"] == 1
    assert out["pagesReturned"] == ""
    assert out["text"] == ""
    assert "can never be returned" in out["note"]
    assert "Do not request this page again" in out["note"]


def test_read_pdf_oversize_middle_page_flagged_in_note():
    data = _pdf_bytes(["short", "x" * 60, "short again"])
    client, _ = _client_for(data)
    out = client.read_content_version_text("068000000000001", 10_000_000, 50)
    assert out["pagesReturned"] == "1"
    assert out["truncated"] is True
    assert out["truncatedAtPage"] == 2
    # Page 2 exceeds the cap even alone, so the dead-end warning fires despite
    # page 1 having been returned.
    assert "Page 2 alone" in out["note"]
    assert "can never be returned" in out["note"]


def test_read_pdf_magic_bytes_beats_wrong_extension():
    data = _pdf_bytes(["disguised pdf"])
    client, _ = _client_for(data, extension="dat")
    out = client.read_content_version_text("068000000000001", 10_000_000, 100_000)
    assert out["mimeType"] == "application/pdf"
    assert "disguised pdf" in out["text"]


def test_read_pdf_no_text_layer_returns_note():
    data = _pdf_bytes(["", ""])
    client, _ = _client_for(data)
    out = client.read_content_version_text("068000000000001", 10_000_000, 100_000)
    assert out["text"] == ""
    assert "OCR" in out["note"]
    assert out["truncated"] is False


def test_read_pdf_user_password_rejected():
    data = _pdf_bytes(["secret"], user_password="hunter2")
    client, _ = _client_for(data)
    with pytest.raises(ValueError, match="password-protected"):
        client.read_content_version_text("068000000000001", 10_000_000, 100_000)


def test_read_pdf_owner_only_password_opens():
    data = _pdf_bytes(["owner locked"], owner_password="hunter2")
    client, _ = _client_for(data)
    out = client.read_content_version_text("068000000000001", 10_000_000, 100_000)
    assert "owner locked" in out["text"]


def test_read_pdf_corrupt_raises():
    client, _ = _client_for(b"%PDF-1.4\nnot really a pdf")
    with pytest.raises(ValueError, match="not a readable PDF"):
        client.read_content_version_text("068000000000001", 10_000_000, 100_000)


# --- non-PDF paths ---


def test_read_text_file_decodes():
    client, _ = _client_for(b"a,b,c\n1,2,3\n", extension="csv")
    out = client.read_content_version_text("068000000000001", 10_000_000, 100_000)
    assert out["text"] == "a,b,c\n1,2,3\n"
    assert out["pageCount"] is None
    assert out["pagesReturned"] is None
    assert out["truncated"] is False
    assert out["mimeType"] == "text/csv"


def test_read_text_file_truncates_at_char_limit():
    client, _ = _client_for(b"x" * 100, extension="txt")
    out = client.read_content_version_text("068000000000001", 10_000_000, 40)
    assert out["truncated"] is True
    assert out["text"] == "x" * 40


def test_read_text_file_rejects_pages():
    client, _ = _client_for(b"plain", extension="txt")
    with pytest.raises(ValueError, match="only applies to PDFs"):
        client.read_content_version_text(
            "068000000000001", 10_000_000, 100_000, pages="1"
        )


def test_read_binary_non_pdf_raises():
    client, _ = _client_for(b"\xff\xfe\x00\x01", extension="bin")
    with pytest.raises(ValueError, match="neither a PDF nor valid UTF-8"):
        client.read_content_version_text("068000000000001", 10_000_000, 100_000)


# --- guards shared with download_file ---


def test_read_rejects_bad_id():
    client = SalesforceClient()
    client._sf = MagicMock()
    with pytest.raises(ValueError, match="Invalid content ID"):
        client.read_content_version_text("123", 10_000_000, 100_000)


def test_read_rejects_oversize_before_fetch():
    client, sf = _client_for(b"irrelevant", size=5000)
    with pytest.raises(ValueError, match="too large"):
        client.read_content_version_text("068000000000001", 1000, 100_000)
    sf._call_salesforce.assert_not_called()
