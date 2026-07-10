"""Tests for PDF merging (merging.py) and the /api/merge endpoint."""

import io

import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import pikepdf
import pytest
from fastapi.testclient import TestClient

import main
import merging

client = TestClient(main.app)


def _make_pdf(n_pages: int = 1) -> bytes:
    pdf = pikepdf.Pdf.new()
    for _ in range(n_pages):
        pdf.add_blank_page()
    buf = io.BytesIO()
    pdf.save(buf)
    return buf.getvalue()


def _make_encrypted_pdf() -> bytes:
    pdf = pikepdf.Pdf.new()
    pdf.add_blank_page()
    buf = io.BytesIO()
    pdf.save(buf, encryption=pikepdf.Encryption(owner="owner", user="secret"))
    return buf.getvalue()


# --- merging.merge_pdfs -----------------------------------------------------

def test_merge_pdfs_concatenates_pages_in_order():
    merged = merging.merge_pdfs([_make_pdf(2), _make_pdf(3)])
    with pikepdf.open(io.BytesIO(merged)) as pdf:
        assert len(pdf.pages) == 5


def test_merge_pdfs_preserves_order_of_three_files():
    merged = merging.merge_pdfs([_make_pdf(1), _make_pdf(2), _make_pdf(1)])
    with pikepdf.open(io.BytesIO(merged)) as pdf:
        assert len(pdf.pages) == 4


def test_merge_pdfs_raises_on_encrypted_input():
    with pytest.raises(merging.EncryptedPdfError):
        merging.merge_pdfs([_make_pdf(1), _make_encrypted_pdf()])


# --- /api/merge endpoint -----------------------------------------------------

def test_merge_endpoint_combines_two_pdfs():
    resp = client.post(
        "/api/merge",
        files=[
            ("files", ("a.pdf", _make_pdf(2), "application/pdf")),
            ("files", ("b.pdf", _make_pdf(1), "application/pdf")),
        ],
    )
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "application/pdf"
    with pikepdf.open(io.BytesIO(resp.content)) as pdf:
        assert len(pdf.pages) == 3


def test_merge_endpoint_rejects_single_file():
    resp = client.post(
        "/api/merge", files=[("files", ("a.pdf", _make_pdf(1), "application/pdf"))]
    )
    assert resp.status_code == 400


def test_merge_endpoint_rejects_non_pdf():
    resp = client.post(
        "/api/merge",
        files=[
            ("files", ("a.pdf", _make_pdf(1), "application/pdf")),
            ("files", ("b.txt", b"hello", "text/plain")),
        ],
    )
    assert resp.status_code == 415


def test_merge_endpoint_reports_422_on_encrypted_pdf():
    resp = client.post(
        "/api/merge",
        files=[
            ("files", ("a.pdf", _make_pdf(1), "application/pdf")),
            ("files", ("b.pdf", _make_encrypted_pdf(), "application/pdf")),
        ],
    )
    assert resp.status_code == 422


def test_merge_endpoint_content_disposition_is_well_formed():
    resp = client.post(
        "/api/merge",
        files=[
            ("files", ("a.pdf", _make_pdf(1), "application/pdf")),
            ("files", ("b.pdf", _make_pdf(1), "application/pdf")),
        ],
    )
    cd = resp.headers["content-disposition"]
    assert "\r" not in cd and "\n" not in cd
    assert 'filename="merged.pdf"' in cd


def test_merge_endpoint_offloads_blocking_work_to_threadpool(monkeypatch):
    calls = []

    async def fake_run_in_threadpool(func, *args):
        calls.append(func)
        return func(*args)

    monkeypatch.setattr(main, "run_in_threadpool", fake_run_in_threadpool)
    resp = client.post(
        "/api/merge",
        files=[
            ("files", ("a.pdf", _make_pdf(1), "application/pdf")),
            ("files", ("b.pdf", _make_pdf(1), "application/pdf")),
        ],
    )
    assert calls, "merge should run the blocking work via run_in_threadpool"
    assert resp.status_code == 200
