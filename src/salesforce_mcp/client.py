"""Salesforce client wrapper with lazy connection, validation, and caching."""

import base64
import binascii
import io
import mimetypes
import os
import re

from pypdf import PdfReader
from pypdf.errors import PyPdfError
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
DEFAULT_MAX_TEXT_CHARS = 100_000


_PAGE_SPEC_PART_RE = re.compile(r"^(\d+)(?:-(\d+))?$")


def _parse_page_spec(spec: str, page_count: int) -> list[int]:
    """Parse a 1-indexed page spec like '3', '1-5', or '2,5-7' into page numbers.

    Preserves the order given, drops duplicates, and validates every page
    against the document's page count so a bad spec fails loudly instead of
    silently returning fewer pages.
    """
    pages: list[int] = []
    seen: set[int] = set()
    for part in spec.split(","):
        match = _PAGE_SPEC_PART_RE.match(part.strip())
        if not match:
            raise ValueError(
                f"Invalid pages value: {spec!r}. Use forms like '3', '1-5', or '2,5-7'."
            )
        start = int(match.group(1))
        end = int(match.group(2) or start)
        if start < 1 or end < start:
            raise ValueError(
                f"Invalid pages value: {spec!r}. Pages are 1-indexed and ranges "
                "must run low to high."
            )
        if end > page_count:
            raise ValueError(
                f"Page {end} is out of range: the PDF has {page_count} page(s)."
            )
        for page in range(start, end + 1):
            if page not in seen:
                seen.add(page)
                pages.append(page)
    if not pages:
        raise ValueError(f"Invalid pages value: {spec!r}.")
    return pages


def _format_page_ranges(pages: list[int]) -> str:
    """Compress a page-number list back into a compact spec, e.g. [1,2,3,5] -> '1-3,5'."""
    ranges: list[str] = []
    start = prev = pages[0]
    for page in pages[1:]:
        if page == prev + 1:
            prev = page
            continue
        ranges.append(str(start) if start == prev else f"{start}-{prev}")
        start = prev = page
    ranges.append(str(start) if start == prev else f"{start}-{prev}")
    return ",".join(ranges)


def _soql_id(value: str) -> str:
    """Validate a Salesforce ID and return it as a quoted SOQL literal.

    The single enforced injection boundary: SOQL has no bind parameters, so every
    ID interpolated into a query goes through here rather than a bare f-string.
    """
    if not _RECORD_ID_RE.match(value):
        raise ValueError(f"Invalid Salesforce ID: {value!r}")
    return f"'{value}'"


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
        soql = (
            "SELECT ContentDocumentId, ContentDocument.LatestPublishedVersionId, "
            "ContentDocument.Title, ContentDocument.FileExtension, "
            "ContentDocument.ContentSize "
            "FROM ContentDocumentLink "
            f"WHERE LinkedEntityId = {_soql_id(record_id)}"
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

    def _fetch_version_bytes(self, content_id: str, max_bytes: int) -> tuple[dict, bytes]:
        """Resolve a content ID to its ContentVersion row and download its bytes.

        Shared fetch core for download_content_version and
        read_content_version_text: validation, 068/069 resolution, size caps,
        and the streamed VersionData request all live here.
        """
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
                f"WHERE Id = {_soql_id(content_id)})"
            )
        else:
            where = f"Id = {_soql_id(content_id)}"
        result = self.sf.query(f"SELECT {cols} FROM ContentVersion WHERE {where}")
        records = result.get("records", [])
        if not records:
            raise ValueError(f"File not found for content ID: {content_id!r}")
        row = records[0]
        size = row.get("ContentSize")
        # Unknown size can't be capped — refuse rather than buffer it all into memory.
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
        # Stream and abort past the cap so a mismatched/redirected payload can't
        # exhaust memory; `with` frees the connection on every exit path.
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
        return row, data

    def download_content_version(self, content_id: str, max_bytes: int) -> dict:
        """Download a file's bytes by ContentVersionId (068) or ContentDocumentId (069)."""
        row, data = self._fetch_version_bytes(content_id, max_bytes)
        extension = row.get("FileExtension") or ""
        title = row.get("Title") or row["Id"]
        filename = f"{title}.{extension}" if extension else title

        # Text-like + valid UTF-8 → readable string; anything else → base64.
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
            "sizeBytes": row.get("ContentSize"),
            "encoding": encoding,
            "content": content,
        }

    def read_content_version_text(
        self,
        content_id: str,
        max_bytes: int,
        max_chars: int,
        pages: str | None = None,
    ) -> dict:
        """Extract readable text from a file: PDFs via pypdf, everything else as UTF-8."""
        row, data = self._fetch_version_bytes(content_id, max_bytes)
        extension = (row.get("FileExtension") or "").lower()
        title = row.get("Title") or row["Id"]
        filename = f"{title}.{extension}" if extension else title

        # Extensions in Salesforce can be missing or wrong; the magic bytes aren't.
        if extension == "pdf" or data.startswith(b"%PDF-"):
            return self._extract_pdf_text(filename, row, data, max_chars, pages)

        if pages is not None:
            raise ValueError(
                f"pages only applies to PDFs; {filename!r} is not a PDF."
            )
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            raise ValueError(
                f"{filename!r} is neither a PDF nor valid UTF-8 text. Use "
                "download_file for its raw contents (base64)."
            ) from None
        truncated = len(text) > max_chars
        return {
            "filename": filename,
            "mimeType": mimetypes.guess_type(filename)[0],
            "sizeBytes": row.get("ContentSize"),
            "pageCount": None,
            "pagesReturned": None,
            "text": text[:max_chars],
            "truncated": truncated,
        }

    def _extract_pdf_text(
        self,
        filename: str,
        row: dict,
        data: bytes,
        max_chars: int,
        pages: str | None,
    ) -> dict:
        try:
            reader = PdfReader(io.BytesIO(data))
        except (PyPdfError, ValueError) as e:
            raise ValueError(f"{filename!r} is not a readable PDF.") from e
        if reader.is_encrypted:
            # Files encrypted with only an owner password open with the empty
            # user password; anything stronger is unreadable without credentials.
            try:
                decrypted = reader.decrypt("")
            except Exception as e:
                raise ValueError(
                    f"{filename!r} is password-protected; cannot extract text."
                ) from e
            if not decrypted:
                raise ValueError(
                    f"{filename!r} is password-protected; cannot extract text."
                )

        page_count = len(reader.pages)
        page_numbers = (
            _parse_page_spec(pages, page_count)
            if pages is not None
            else list(range(1, page_count + 1))
        )

        parts: list[str] = []
        included: list[int] = []
        total = 0
        truncated = False
        truncated_at = None
        has_content = False
        for number in page_numbers:
            try:
                page_text = reader.pages[number - 1].extract_text() or ""
            except Exception as e:
                raise ValueError(
                    f"Failed to extract text from page {number} of {filename!r}."
                ) from e
            if page_text.strip():
                has_content = True
            piece = f"--- page {number} ---\n\n{page_text}"
            if parts:
                piece = "\n\n" + piece
            if total + len(piece) > max_chars:
                parts.append(piece[: max_chars - total])
                included.append(number)
                truncated = True
                truncated_at = number
                break
            parts.append(piece)
            included.append(number)
            total += len(piece)

        result = {
            "filename": filename,
            "mimeType": "application/pdf",
            "sizeBytes": row.get("ContentSize"),
            "pageCount": page_count,
            "pagesReturned": _format_page_ranges(included) if included else "",
            "text": "".join(parts),
            "truncated": truncated,
        }
        if truncated:
            result["truncatedAtPage"] = truncated_at
        elif not has_content:
            # Page markers alone aren't content — return empty text so agents
            # don't mistake the markers for the document.
            result["text"] = ""
            result["note"] = (
                "No extractable text found; this PDF likely contains scanned "
                "images. OCR is not supported."
            )
        return result

    def upload_content_version(
        self,
        filename: str,
        content: str,
        encoding: str,
        max_bytes: int,
        record_id: str | None = None,
    ) -> dict:
        """Upload a file as a ContentVersion, optionally attaching it to a record."""
        # Validate record_id up front so we never create an orphan file we can't link.
        if record_id is not None and not _RECORD_ID_RE.match(record_id):
            raise ValueError(f"Invalid Salesforce record ID: {record_id!r}")

        # Keep only the base name — don't persist caller paths/drive prefixes.
        filename = os.path.basename(filename.replace("\\", "/")).strip()
        if not filename:
            raise ValueError("filename must be a non-empty file name.")

        if encoding == "text":
            data = content.encode("utf-8")
        elif encoding == "base64":
            try:
                data = base64.b64decode(content, validate=True)
            except (binascii.Error, ValueError) as e:
                raise ValueError(
                    "content is not valid base64; pass encoding='text' for plain text."
                ) from e
        else:
            raise ValueError(
                f"Invalid encoding: {encoding!r}. Must be 'base64' or 'text'."
            )

        if len(data) > max_bytes:
            raise ValueError(
                f"File is too large to upload: {len(data)} bytes (limit {max_bytes}). "
                "Raise SALESFORCE_MAX_DOWNLOAD_BYTES to override."
            )

        stem, dot_ext = os.path.splitext(filename)
        title = stem or filename
        version = self.sf.ContentVersion.create(
            {
                "Title": title,
                "PathOnClient": filename,
                "VersionData": base64.b64encode(data).decode("ascii"),
            }
        )
        version_id = version["id"]
        # Any post-create failure can orphan the file; best-effort roll it back
        # once the document id is known.
        document_id = None
        try:
            records = self.sf.query(
                f"SELECT ContentDocumentId FROM ContentVersion WHERE Id = {_soql_id(version_id)}"
            ).get("records", [])
            document_id = records[0].get("ContentDocumentId") if records else None
            if not document_id:
                raise ValueError(
                    f"Uploaded ContentVersion {version_id} but could not resolve its "
                    "ContentDocumentId (the file may need manual cleanup)."
                )

            linked_entity_id = None
            if record_id is not None:
                self.sf.ContentDocumentLink.create(
                    {
                        "ContentDocumentId": document_id,
                        "LinkedEntityId": record_id,
                        "ShareType": "V",
                        # Least-privilege: internal users only, not external/community.
                        "Visibility": "InternalUsers",
                    }
                )
                linked_entity_id = record_id
        except Exception:
            if document_id:
                try:
                    self.sf.ContentDocument.delete(document_id)
                except Exception:
                    pass
            raise

        return {
            "contentVersionId": version_id,
            "contentDocumentId": document_id,
            "title": title,
            "fileExtension": dot_ext.lstrip("."),
            "linkedEntityId": linked_entity_id,
        }


# Module-level singleton
client = SalesforceClient()
