"""Unit tests for SalesforceClient file methods (mocked, no live org)."""

import base64
from unittest.mock import MagicMock

import pytest

from salesforce_mcp.client import SalesforceClient, _soql_id
from tests.pdf_fixtures import pdf_bytes


def test_soql_id_quotes_valid_ids():
    assert _soql_id("068000000000001") == "'068000000000001'"
    assert _soql_id("001000000000001AAA") == "'001000000000001AAA'"


def test_soql_id_rejects_invalid_and_injection():
    for bad in ["", "not-an-id!", "068' OR '1'='1", "12345", "0680000000000012"]:
        with pytest.raises(ValueError, match="Invalid Salesforce ID"):
            _soql_id(bad)


def _client_with_sf(sf):
    c = SalesforceClient()
    c._sf = sf
    return c


def _stream_resp(*chunks):
    """A mock streamed Response usable as a context manager, yielding `chunks`."""
    resp = MagicMock()
    resp.__enter__.return_value = resp
    resp.iter_content.return_value = list(chunks)
    return resp


def _version_query_result(**overrides):
    row = {
        "Id": "068000000000001",
        "Title": "report",
        "FileExtension": "pdf",
        "ContentSize": 10,
    }
    row.update(overrides)
    return {"totalSize": 1, "records": [row]}


def test_list_record_files_maps_fields_and_pages():
    sf = MagicMock()
    sf.query_all.return_value = {
        "totalSize": 1,
        "records": [
            {
                "ContentDocumentId": "069000000000001",
                "ContentDocument": {
                    "LatestPublishedVersionId": "068000000000001",
                    "Title": "spec",
                    "FileExtension": "pdf",
                    "ContentSize": 2048,
                },
            }
        ],
    }
    c = _client_with_sf(sf)
    files = c.list_record_files("001000000000001")
    assert files == [
        {
            "contentVersionId": "068000000000001",
            "contentDocumentId": "069000000000001",
            "title": "spec",
            "fileExtension": "pdf",
            "sizeBytes": 2048,
        }
    ]
    # Must page through all rows, not just the first query batch.
    sf.query_all.assert_called_once()
    sf.query.assert_not_called()


def test_list_record_files_rejects_bad_id():
    c = _client_with_sf(MagicMock())
    with pytest.raises(ValueError):
        c.list_record_files("not-an-id!")


def test_download_rejects_bad_id():
    c = _client_with_sf(MagicMock())
    with pytest.raises(ValueError):
        c.download_content_version("123", max_bytes=1000)


def test_download_rejects_oversize_before_fetch():
    sf = MagicMock()
    sf.query.return_value = _version_query_result(ContentSize=5000)
    c = _client_with_sf(sf)
    with pytest.raises(ValueError, match="too large"):
        c.download_content_version("068000000000001", max_bytes=1000)
    sf._call_salesforce.assert_not_called()


def test_download_text_file_returns_decoded_string():
    sf = MagicMock()
    sf.query.return_value = _version_query_result(FileExtension="csv", ContentSize=5)
    sf.base_url = "https://x.my.salesforce.com/services/data/v59.0/"
    sf.headers = {"Authorization": "Bearer t"}
    sf._call_salesforce.return_value = _stream_resp(b"a,b,c")
    c = _client_with_sf(sf)
    out = c.download_content_version("068000000000001", max_bytes=1000)
    assert out["encoding"] == "text"
    assert out["content"] == "a,b,c"
    assert out["filename"] == "report.csv"


def test_download_binary_file_returns_base64():
    sf = MagicMock()
    sf.query.return_value = _version_query_result(FileExtension="pdf", ContentSize=4)
    sf.base_url = "https://x.my.salesforce.com/services/data/v59.0/"
    sf.headers = {"Authorization": "Bearer t"}
    sf._call_salesforce.return_value = _stream_resp(b"\x89PNG")
    c = _client_with_sf(sf)
    out = c.download_content_version("068000000000001", max_bytes=1000)
    assert out["encoding"] == "base64"
    assert base64.b64decode(out["content"]) == b"\x89PNG"


def test_download_text_ext_but_binary_bytes_falls_back_to_base64():
    sf = MagicMock()
    sf.query.return_value = _version_query_result(FileExtension="csv", ContentSize=2)
    sf.base_url = "https://x.my.salesforce.com/services/data/v59.0/"
    sf.headers = {"Authorization": "Bearer t"}
    sf._call_salesforce.return_value = _stream_resp(b"\xff\xfe")  # not valid UTF-8
    c = _client_with_sf(sf)
    out = c.download_content_version("068000000000001", max_bytes=1000)
    assert out["encoding"] == "base64"


def test_download_not_found_raises():
    sf = MagicMock()
    sf.query.return_value = {"totalSize": 0, "records": []}
    c = _client_with_sf(sf)
    with pytest.raises(ValueError, match="not found"):
        c.download_content_version("069000000000001", max_bytes=1000)


def test_download_unknown_size_rejected_before_fetch():
    sf = MagicMock()
    sf.query.return_value = _version_query_result(ContentSize=None)
    c = _client_with_sf(sf)
    with pytest.raises(ValueError, match="size unknown"):
        c.download_content_version("068000000000001", max_bytes=1000)
    sf._call_salesforce.assert_not_called()


def test_download_rejects_oversize_actual_payload():
    # ContentSize passes the pre-check, but the real payload exceeds the cap.
    sf = MagicMock()
    sf.query.return_value = _version_query_result(FileExtension="pdf", ContentSize=4)
    sf._call_salesforce.return_value = _stream_resp(b"x" * 5000)
    c = _client_with_sf(sf)
    with pytest.raises(ValueError, match="exceeds the size limit"):
        c.download_content_version("068000000000001", max_bytes=1000)


def test_download_includes_mime_type():
    sf = MagicMock()
    sf.query.return_value = _version_query_result(FileExtension="pdf", ContentSize=4)
    sf._call_salesforce.return_value = _stream_resp(b"\x89PDF")
    c = _client_with_sf(sf)
    out = c.download_content_version("068000000000001", max_bytes=1000)
    assert out["mimeType"] == "application/pdf"


def test_download_document_id_uses_latest_published_version():
    sf = MagicMock()
    sf.query.return_value = _version_query_result(FileExtension="pdf", ContentSize=4)
    sf._call_salesforce.return_value = _stream_resp(b"data")
    c = _client_with_sf(sf)
    c.download_content_version("069000000000001", max_bytes=1000)
    soql = sf.query.call_args[0][0]
    assert "LatestPublishedVersionId" in soql
    assert "IsLatest" not in soql


# --- download_content_version, mode="read" ---


def _client_with_file(data: bytes, **row):
    sf = MagicMock()
    sf.query.return_value = _version_query_result(ContentSize=len(data), **row)
    sf._call_salesforce.return_value = _stream_resp(data)
    return _client_with_sf(sf), sf


def test_read_mode_returns_page_text_and_pdf_block():
    data = pdf_bytes(["alpha", "beta"])
    c, _ = _client_with_file(data)
    out = c.download_content_version("068000000000001", max_bytes=10**6, mode="read")
    assert list(out) == [
        "filename", "fileExtension", "mimeType", "sizeBytes", "encoding", "content", "pdf",
    ]
    assert out["filename"] == "report.pdf"
    assert out["sizeBytes"] == len(data)
    assert out["encoding"] == "text"
    assert out["content"].startswith("--- Page 1 of 2 ---\nalpha")
    assert "--- Page 2 of 2 ---\nbeta" in out["content"]
    assert out["pdf"] == {
        "totalPages": 2,
        "pages": [
            {"page": 1, "truncated": False, "hasImages": False},
            {"page": 2, "truncated": False, "hasImages": False},
        ],
        "truncated": False,
        "nextPage": None,
        "stopReason": "complete",
        "warnings": [],
    }


def test_read_mode_start_page():
    c, _ = _client_with_file(pdf_bytes(["alpha", "beta"]))
    out = c.download_content_version(
        "068000000000001", max_bytes=10**6, mode="read", start_page=2
    )
    assert out["content"].startswith("--- Page 2 of 2 ---")
    assert [p["page"] for p in out["pdf"]["pages"]] == [2]


def test_read_mode_detects_pdf_by_magic_bytes_despite_extension():
    c, _ = _client_with_file(pdf_bytes(["alpha"]), FileExtension="docx")
    out = c.download_content_version("068000000000001", max_bytes=10**6, mode="read")
    assert out["mimeType"] == "application/pdf"
    assert out["pdf"]["totalPages"] == 1


def test_read_mode_rejects_non_pdf():
    c, _ = _client_with_file(b"a,b\n1,2\n", FileExtension="csv")
    with pytest.raises(ValueError, match='mode="download"'):
        c.download_content_version("068000000000001", max_bytes=1000, mode="read")


def test_read_mode_rejects_oversize_before_fetch():
    sf = MagicMock()
    sf.query.return_value = _version_query_result(ContentSize=5000)
    c = _client_with_sf(sf)
    with pytest.raises(ValueError, match="too large"):
        c.download_content_version("068000000000001", max_bytes=1000, mode="read")
    sf._call_salesforce.assert_not_called()


def test_start_page_in_download_mode_rejected_before_any_salesforce_call():
    sf = MagicMock()
    c = _client_with_sf(sf)
    with pytest.raises(ValueError, match="start_page is only used with"):
        c.download_content_version("068000000000001", max_bytes=1000, start_page=2)
    sf.query.assert_not_called()


def test_invalid_mode_rejected():
    c = _client_with_sf(MagicMock())
    with pytest.raises(ValueError, match="Invalid mode"):
        c.download_content_version("068000000000001", max_bytes=1000, mode="ocr")


def test_download_mode_output_unchanged_for_pdf():
    data = pdf_bytes(["alpha"])
    c, _ = _client_with_file(data)
    out = c.download_content_version("068000000000001", max_bytes=10**6)
    assert out == {
        "filename": "report.pdf",
        "fileExtension": "pdf",
        "mimeType": "application/pdf",
        "sizeBytes": len(data),
        "encoding": "base64",
        "content": base64.b64encode(data).decode("ascii"),
    }
