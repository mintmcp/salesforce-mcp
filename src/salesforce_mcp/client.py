"""Salesforce client wrapper with lazy connection, validation, and caching."""

import base64
import mimetypes
import re

from simple_salesforce import Salesforce
from simple_salesforce.api import SFType

from salesforce_mcp.auth import create_salesforce_client

_OBJECT_NAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]*$")
# Salesforce IDs are exactly 15 or 18 chars; ContentVersion=068, ContentDocument=069.
_CONTENT_ID_RE = re.compile(r"^06[89][A-Za-z0-9]{12}(?:[A-Za-z0-9]{3})?$")
_RECORD_ID_RE = re.compile(r"^[A-Za-z0-9]{15}(?:[A-Za-z0-9]{3})?$")

TEXT_EXTENSIONS = frozenset(
    {
        "csv", "json", "xml", "txt", "html", "md", "log", "yaml", "yml", "tsv",
        "py", "js", "ts", "sql", "sh", "ini", "cfg", "toml",
    }
)
DEFAULT_MAX_DOWNLOAD_BYTES = 10 * 1024 * 1024


class SalesforceClient:
    def __init__(self) -> None:
        self._sf: Salesforce | None = None
        self._describe_cache: dict[str, dict] = {}

    @property
    def sf(self) -> Salesforce:
        """Lazy Salesforce connection — connects on first access."""
        if self._sf is None:
            self._sf = create_salesforce_client()
        return self._sf

    def get_sf_object(self, object_name: str) -> SFType:
        """Get a Salesforce object by name with validation."""
        if not _OBJECT_NAME_RE.match(object_name):
            raise ValueError(f"Invalid Salesforce object name: {object_name!r}")
        obj = getattr(self.sf, object_name)
        if not isinstance(obj, SFType):
            raise ValueError(f"Not a valid Salesforce object: {object_name!r}")
        return obj

    def list_objects(self, search: str | None = None) -> list[dict]:
        """List all SObjects in the org, optionally filtered by substring."""
        result = self.sf.describe()
        sobjects = []
        for obj in result["sobjects"]:
            entry = {
                "name": obj["name"],
                "label": obj["label"],
                "queryable": obj["queryable"],
                "createable": obj["createable"],
                "custom": obj["custom"],
            }
            if search:
                search_lower = search.lower()
                if (
                    search_lower not in entry["name"].lower()
                    and search_lower not in entry["label"].lower()
                ):
                    continue
            sobjects.append(entry)
        return sobjects

    def describe_object(self, object_name: str) -> dict:
        """Get full describe metadata for an object (cached)."""
        if object_name not in self._describe_cache:
            sf_object = self.get_sf_object(object_name)
            desc = sf_object.describe()
            self._describe_cache[object_name] = {
                "fields": desc["fields"],
                "childRelationships": desc.get("childRelationships", []),
                "recordTypeInfos": desc.get("recordTypeInfos", []),
            }
        return self._describe_cache[object_name]

    def list_record_files(self, record_id: str) -> list[dict]:
        """List files (ContentDocuments) attached to a record."""
        if not _RECORD_ID_RE.match(record_id):
            raise ValueError(f"Invalid Salesforce record ID: {record_id!r}")
        soql = (
            "SELECT ContentDocumentId, ContentDocument.LatestPublishedVersionId, "
            "ContentDocument.Title, ContentDocument.FileExtension, "
            "ContentDocument.ContentSize "
            "FROM ContentDocumentLink "
            f"WHERE LinkedEntityId = '{record_id}'"
        )
        # query_all pages through all ContentDocumentLink rows, not just the first batch.
        result = self.sf.query_all(soql)
        files = []
        for row in result.get("records", []):
            doc = row.get("ContentDocument") or {}
            files.append(
                {
                    "contentVersionId": doc.get("LatestPublishedVersionId"),
                    "contentDocumentId": row.get("ContentDocumentId"),
                    "title": doc.get("Title"),
                    "fileExtension": doc.get("FileExtension"),
                    "sizeBytes": doc.get("ContentSize"),
                }
            )
        return files

    def download_content_version(self, content_id: str, max_bytes: int) -> dict:
        """Download a file's bytes by ContentVersionId (068) or ContentDocumentId (069)."""
        if not _CONTENT_ID_RE.match(content_id):
            raise ValueError(
                f"Invalid content ID: {content_id!r}. Expected a ContentVersionId "
                "(068...) or ContentDocumentId (069...)."
            )
        cols = "Id, Title, FileExtension, ContentSize"
        if content_id.startswith("069"):
            # Resolve the document's latest *published* version (matches list_files).
            where = (
                "Id IN (SELECT LatestPublishedVersionId FROM ContentDocument "
                f"WHERE Id = '{content_id}')"
            )
        else:
            where = f"Id = '{content_id}'"
        result = self.sf.query(f"SELECT {cols} FROM ContentVersion WHERE {where}")
        records = result.get("records", [])
        if not records:
            raise ValueError(f"File not found for content ID: {content_id!r}")
        row = records[0]
        size = row.get("ContentSize")
        # A missing size can't be checked against the cap — refuse rather than
        # buffer an unbounded download into memory.
        if size is None:
            raise ValueError(
                f"File size unknown for content ID: {content_id!r}; refusing to download."
            )
        if size > max_bytes:
            raise ValueError(
                f"File is too large to download inline: {size} bytes "
                f"(limit {max_bytes}). Raise SALESFORCE_MAX_DOWNLOAD_BYTES to override."
            )
        version_id = row["Id"]
        url = f"{self.sf.base_url}sobjects/ContentVersion/{version_id}/VersionData"
        # Route through simple_salesforce so Salesforce errors are normalized. Stream
        # and abort past the cap so a redirected/mismatched VersionData payload can't
        # exhaust connector memory (ContentSize is metadata, not a payload guarantee).
        # `with` releases the streamed connection on every exit path (success,
        # cap abort, or a mid-stream network error).
        with self.sf._call_salesforce(
            "GET", url, name="download_content_version", stream=True
        ) as resp:
            chunks = []
            total = 0
            for chunk in resp.iter_content(chunk_size=65536):
                total += len(chunk)
                if total > max_bytes:
                    raise ValueError(
                        f"Downloaded file exceeds the size limit: over {max_bytes} "
                        "bytes. Raise SALESFORCE_MAX_DOWNLOAD_BYTES to override."
                    )
                chunks.append(chunk)
            data = b"".join(chunks)

        extension = row.get("FileExtension") or ""
        title = row.get("Title") or version_id
        filename = f"{title}.{extension}" if extension else title

        # Decode text-like files to a readable string; base64 everything else,
        # including text files whose bytes aren't valid UTF-8.
        if extension.lower() in TEXT_EXTENSIONS:
            try:
                content, encoding = data.decode("utf-8"), "text"
            except UnicodeDecodeError:
                content, encoding = base64.b64encode(data).decode("ascii"), "base64"
        else:
            content, encoding = base64.b64encode(data).decode("ascii"), "base64"

        mime_type = mimetypes.guess_type(filename)[0]
        return {
            "filename": filename,
            "fileExtension": extension,
            "mimeType": mime_type,
            "sizeBytes": size,
            "encoding": encoding,
            "content": content,
        }


# Module-level singleton
client = SalesforceClient()
