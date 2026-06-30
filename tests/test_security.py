"""Security-focused smoke tests for the Doc2MD backend.

These exercise the hardening guards added for untrusted PDF/DOCX uploads:
the Ghostscript sandbox flag, the DOCX zip-bomb cap, the Pillow pixel cap,
and Content-Disposition header sanitization — plus basic round-trip behaviour.
"""

import io
import zipfile

import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import pytest
from fastapi.testclient import TestClient
from PIL import Image

import compression
import main

client = TestClient(main.app)

DOCX_MEDIA_TYPE = (
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
)


def _make_docx(extra: dict[str, bytes] | None = None) -> bytes:
    """Build a minimal valid DOCX, optionally with extra archive members."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", "<Types/>")
        z.writestr("word/document.xml", "<w:document/>")
        for name, data in (extra or {}).items():
            z.writestr(name, data)
    return buf.getvalue()


# --- Guard 1: Pillow decompression-bomb cap -------------------------------

def test_pillow_pixel_cap_is_set():
    assert Image.MAX_IMAGE_PIXELS == 50_000_000


# --- Guard 2: Ghostscript runs sandboxed ----------------------------------

def test_ghostscript_command_uses_safer(monkeypatch):
    captured = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        out_path = next(a.split("=", 1)[1] for a in cmd if a.startswith("-sOutputFile="))
        with open(out_path, "wb") as fh:
            fh.write(b"%PDF-1.4\n%%EOF\n")

        class _Result:
            returncode = 0

        return _Result()

    monkeypatch.setattr(compression.subprocess, "run", fake_run)
    compression._compress_pdf_ghostscript(b"%PDF-1.4\n%%EOF\n", "ebook")
    assert "-dSAFER" in captured["cmd"]


# --- Guard 3: DOCX zip-bomb cap -------------------------------------------

def test_docx_zip_bomb_is_rejected(monkeypatch):
    # Lower the cap so the test stays small and fast.
    monkeypatch.setattr(compression, "_DOCX_MAX_UNCOMPRESSED_BYTES", 1_000)
    bomb = _make_docx({"word/big.bin": b"\0" * 5_000})
    with pytest.raises(ValueError):
        compression.compress_docx(bomb)


def test_normal_docx_is_not_rejected():
    # A small, legitimate DOCX round-trips to a valid archive.
    out = compression.compress_docx(_make_docx())
    assert zipfile.ZipFile(io.BytesIO(out)).testzip() is None


# --- Guard 4: Content-Disposition header sanitization ---------------------

def test_content_disposition_blocks_crlf_and_quote_injection():
    header = main._content_disposition('evil";\r\nX-Injected: 1-compressed.docx')
    assert "\r" not in header and "\n" not in header
    # The ASCII fallback must not contain a raw quote that breaks out of the field.
    fallback = header.split('filename="', 1)[1].split('"', 1)[0]
    assert '"' not in fallback and ";" not in fallback


def test_compress_endpoint_header_is_well_formed():
    resp = client.post(
        "/api/compress",
        files={"file": ('weird name.docx', _make_docx(), DOCX_MEDIA_TYPE)},
    )
    assert resp.status_code == 200
    cd = resp.headers["content-disposition"]
    assert "\r" not in cd and "\n" not in cd
    assert "filename*=UTF-8''" in cd


# --- Regression guards on the endpoints -----------------------------------

def test_convert_rejects_unsupported_type():
    resp = client.post(
        "/api/convert", files={"file": ("note.txt", b"hello", "text/plain")}
    )
    assert resp.status_code == 415


def test_compress_rejects_legacy_doc():
    resp = client.post(
        "/api/compress", files={"file": ("old.doc", _make_docx(), "application/msword")}
    )
    assert resp.status_code == 415


def test_compress_rejects_invalid_quality():
    resp = client.post(
        "/api/compress?quality=ultra",
        files={"file": ("a.docx", _make_docx(), DOCX_MEDIA_TYPE)},
    )
    assert resp.status_code == 422


def test_compress_never_returns_larger_than_input():
    data = _make_docx()
    resp = client.post(
        "/api/compress", files={"file": ("a.docx", data, DOCX_MEDIA_TYPE)}
    )
    assert resp.status_code == 200
    assert int(resp.headers["x-compressed-size"]) <= int(resp.headers["x-original-size"])


# --- Ghostscript timeout reporting -----------------------------------------

def test_ghostscript_timeout_raises_distinct_exception(monkeypatch):
    import subprocess as sp

    def fake_run(cmd, **kwargs):
        raise sp.TimeoutExpired(cmd, kwargs.get("timeout"))

    monkeypatch.setattr(compression.subprocess, "run", fake_run)
    with pytest.raises(compression.GhostscriptTimeout):
        compression._compress_pdf_ghostscript(b"%PDF-1.4\n%%EOF\n", "ebook")


def test_compress_endpoint_reports_504_on_ghostscript_timeout(monkeypatch):
    def fake_compress_pdf(data, quality):
        raise compression.GhostscriptTimeout("boom")

    monkeypatch.setattr(main.compression, "compress_pdf", fake_compress_pdf)
    resp = client.post(
        "/api/compress",
        files={"file": ("big.pdf", b"%PDF-1.4\n%%EOF\n", "application/pdf")},
    )
    assert resp.status_code == 504
    assert "timed out" in resp.json()["detail"].lower()
