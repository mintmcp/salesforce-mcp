"""Unit tests for the filename sanitizer shared by the upload and download paths."""

import pytest

from salesforce_mcp.client import _MAX_FILENAME_BYTES, _safe_filename


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("report.pdf", "report.pdf"),
        ("/Users/alice/secrets/report.pdf", "report.pdf"),
        ("C:\\Users\\alice\\report.csv", "report.csv"),
        ("../../../.ssh/authorized_keys", "authorized_keys"),
        ("re\x00po\x1frt\n.csv", "report.csv"),
        # A leading dot is a real name; an all-dot name is a directory.
        ("../../.env", ".env"),
        (".", ""),
        ("..", ""),
        ("...", ""),
        ("", ""),
        ("   ", ""),
        # Drive-relative resolves via the Windows basename; the NTFS stream form
        # is not a drive, so the colon itself has to go.
        ("C:evil.exe", "evil.exe"),
        ("notes.txt:evil.exe", "notes.txtevil.exe"),
        # Win32 drops trailing dots/spaces, landing the file under another name.
        ("evil.exe.", "evil.exe"),
        ("report.txt ", "report.txt"),
        # Reserved device names are not writable as files on Windows.
        ("CON", ""),
        ("con.txt", ""),
        ("lpt1.log", ""),
        # Bidi overrides make the rendered extension differ from the real one.
        ("report\u202egnp.exe", "reportgnp.exe"),
        ("a\u200bb.txt", "ab.txt"),
        # Compatibility forms decompose into separators after basename() runs.
        ("\uff0e\uff0e\uff0f\uff0e\uff0e\uff0fetc\uff0fpasswd", "passwd"),
        # Not writable on Win32.
        ('re*p?o"r<t>|.txt', "report.txt"),
        # NFKC expands these into the characters above.
        ("x⁇y.txt", "xy.txt"),
        ("x｜y.txt", "xy.txt"),
        ("x﹡y.txt", "xy.txt"),
        ("x＂y.txt", "xy.txt"),
        ("x＜y＞z.txt", "xyz.txt"),
        # Win32 trims a component's trailing spaces before resolving the device.
        ("con .txt", ""),
        ("CON .txt", ""),
        ("com1 .txt", ""),
        # NFKC folds these spaces to U+0020.
        ("con\xa0.txt", ""),
        ("con　.txt", ""),
        # Unencodable.
        ("\ud800evil.txt", "evil.txt"),
        (".. .", ""),
        (". .", ""),
        ("a. .", "a"),
        # Invisible: two distinct titles would render identically.
        ("report­.pdf", "report.pdf"),
        ("report؜.pdf", "report.pdf"),
        ("reportㅤ.pdf", "report.pdf"),
    ],
)
def test_safe_filename(raw, expected):
    assert _safe_filename(raw) == expected


@pytest.mark.parametrize(
    "raw",
    ["x⁇y.txt", "con\xa0.txt", "\ud800evil.txt", "../../.env", "reportㅤ.pdf", ".. ."],
)
def test_safe_filename_is_idempotent(raw):
    once = _safe_filename(raw)
    assert _safe_filename(once) == once


def test_safe_filename_truncates_to_the_byte_limit_keeping_the_extension():
    out = _safe_filename("a" * 400 + ".txt")
    assert len(out.encode("utf-8")) <= _MAX_FILENAME_BYTES
    assert out.endswith(".txt")


@pytest.mark.parametrize("raw", ["a" * 254 + "." + "b" * 200, "a" * 254 + " ." + "b" * 200])
def test_safe_filename_truncation_leaves_no_trailing_dot_or_space(raw):
    out = _safe_filename(raw)
    assert len(out.encode("utf-8")) <= _MAX_FILENAME_BYTES
    assert out == out.rstrip(". ")


def test_safe_filename_truncation_does_not_split_a_multibyte_char():
    out = _safe_filename("é" * 300 + ".txt")
    assert len(out.encode("utf-8")) <= _MAX_FILENAME_BYTES
    assert out.endswith(".txt")
    out.encode("utf-8").decode("utf-8")
