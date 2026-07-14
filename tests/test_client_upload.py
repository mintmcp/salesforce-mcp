"""Unit tests for SalesforceClient.upload_content_version (mocked, no live org)."""

import base64
from unittest.mock import MagicMock

import pytest

from salesforce_mcp.client import SalesforceClient


def _client_with_sf(sf):
    c = SalesforceClient()
    c._sf = sf
    return c


def _sf_for_upload(version_id="068000000000001", document_id="069000000000001"):
    """A mock sf where ContentVersion.create succeeds and its document id resolves."""
    sf = MagicMock()
    sf.ContentVersion.create.return_value = {"id": version_id, "success": True}
    sf.query.return_value = {
        "totalSize": 1,
        "records": [{"ContentDocumentId": document_id}],
    }
    return sf


def test_upload_base64_decodes_and_creates():
    sf = _sf_for_upload()
    c = _client_with_sf(sf)
    payload = base64.b64encode(b"\x00\x01\x02").decode("ascii")
    out = c.upload_content_version("blob.bin", payload, "base64", max_bytes=1000)
    # VersionData sent to Salesforce is the base64 of the decoded bytes.
    sent = sf.ContentVersion.create.call_args[0][0]
    assert base64.b64decode(sent["VersionData"]) == b"\x00\x01\x02"
    assert sent["PathOnClient"] == "blob.bin"
    assert out["contentVersionId"] == "068000000000001"
    assert out["contentDocumentId"] == "069000000000001"
    assert out["fileExtension"] == "bin"
    assert out["title"] == "blob"
    assert out["linkedEntityId"] is None


def test_upload_text_utf8_encodes():
    sf = _sf_for_upload()
    c = _client_with_sf(sf)
    out = c.upload_content_version("note.txt", "hello, world", "text", max_bytes=1000)
    sent = sf.ContentVersion.create.call_args[0][0]
    assert base64.b64decode(sent["VersionData"]) == b"hello, world"
    assert out["fileExtension"] == "txt"


def test_upload_rejects_invalid_base64():
    sf = _sf_for_upload()
    c = _client_with_sf(sf)
    with pytest.raises(ValueError, match="not valid base64"):
        c.upload_content_version("x.bin", "not!base64!", "base64", max_bytes=1000)
    sf.ContentVersion.create.assert_not_called()


def test_upload_rejects_bad_encoding():
    sf = _sf_for_upload()
    c = _client_with_sf(sf)
    with pytest.raises(ValueError, match="encoding"):
        c.upload_content_version("x.txt", "hi", "rot13", max_bytes=1000)
    sf.ContentVersion.create.assert_not_called()


def test_upload_rejects_oversize_before_create():
    sf = _sf_for_upload()
    c = _client_with_sf(sf)
    big = base64.b64encode(b"x" * 5000).decode("ascii")
    with pytest.raises(ValueError, match="too large"):
        c.upload_content_version("big.bin", big, "base64", max_bytes=1000)
    sf.ContentVersion.create.assert_not_called()


def test_upload_rejects_bad_record_id_before_create():
    sf = _sf_for_upload()
    c = _client_with_sf(sf)
    with pytest.raises(ValueError, match="record ID"):
        c.upload_content_version(
            "x.txt", "hi", "text", max_bytes=1000, record_id="bad!"
        )
    sf.ContentVersion.create.assert_not_called()


def test_upload_links_to_record_when_record_id_given():
    sf = _sf_for_upload()
    c = _client_with_sf(sf)
    out = c.upload_content_version(
        "note.txt", "hi", "text", max_bytes=1000, record_id="001000000000001"
    )
    link = sf.ContentDocumentLink.create.call_args[0][0]
    assert link["ContentDocumentId"] == "069000000000001"
    assert link["LinkedEntityId"] == "001000000000001"
    assert link["ShareType"] == "V"
    assert link["Visibility"] == "InternalUsers"
    assert out["linkedEntityId"] == "001000000000001"


def test_upload_no_link_when_record_id_absent():
    sf = _sf_for_upload()
    c = _client_with_sf(sf)
    c.upload_content_version("note.txt", "hi", "text", max_bytes=1000)
    sf.ContentDocumentLink.create.assert_not_called()


def test_upload_rolls_back_file_when_attach_fails():
    sf = _sf_for_upload()
    sf.ContentDocumentLink.create.side_effect = RuntimeError("link failed")
    c = _client_with_sf(sf)
    with pytest.raises(RuntimeError, match="link failed"):
        c.upload_content_version(
            "note.txt", "hi", "text", max_bytes=1000, record_id="001000000000001"
        )
    # The orphaned document must be cleaned up.
    sf.ContentDocument.delete.assert_called_once_with("069000000000001")


def test_upload_strips_path_from_filename():
    sf = _sf_for_upload()
    c = _client_with_sf(sf)
    out = c.upload_content_version(
        "/Users/alice/secrets/report.pdf", "aGk=", "base64", max_bytes=1000
    )
    sent = sf.ContentVersion.create.call_args[0][0]
    assert sent["PathOnClient"] == "report.pdf"
    assert sent["Title"] == "report"
    assert out["fileExtension"] == "pdf"


def test_upload_strips_windows_path_from_filename():
    sf = _sf_for_upload()
    c = _client_with_sf(sf)
    c.upload_content_version(
        "C:\\Users\\alice\\report.csv", "aGk=", "base64", max_bytes=1000
    )
    assert sf.ContentVersion.create.call_args[0][0]["PathOnClient"] == "report.csv"


def test_upload_rejects_empty_filename():
    sf = _sf_for_upload()
    c = _client_with_sf(sf)
    with pytest.raises(ValueError, match="non-empty file name"):
        c.upload_content_version("   ", "aGk=", "base64", max_bytes=1000)
    sf.ContentVersion.create.assert_not_called()


def test_upload_raises_when_document_id_unresolved():
    sf = _sf_for_upload()
    sf.query.return_value = {"totalSize": 0, "records": []}
    c = _client_with_sf(sf)
    with pytest.raises(ValueError, match="could not resolve"):
        c.upload_content_version("note.txt", "hi", "text", max_bytes=1000)
