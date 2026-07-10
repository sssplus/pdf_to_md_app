"""PDF merging helpers for the Doc2MD service.

Concatenates two or more PDFs, in the given order, into a single PDF using
pikepdf (already a dependency of ``compression.py``, so no new package is
required).
"""

from __future__ import annotations

import io

import pikepdf

# Minimum number of PDFs a merge request must supply.
MIN_MERGE_FILES = 2


class EncryptedPdfError(Exception):
    """Raised when one of the input PDFs is password-protected."""


def merge_pdfs(files: list[bytes]) -> bytes:
    """Concatenate PDFs, in order, into a single PDF and return its bytes.

    Raises ``EncryptedPdfError`` if any input requires a password to open —
    pikepdf can't merge pages it can't decrypt, so this is reported as a
    distinct, actionable error rather than a generic failure.
    """
    with pikepdf.Pdf.new() as out:
        for data in files:
            try:
                with pikepdf.open(io.BytesIO(data)) as src:
                    out.pages.extend(src.pages)
            except pikepdf.PasswordError as exc:
                raise EncryptedPdfError(
                    "One of the PDFs is password-protected and can't be merged."
                ) from exc
        buf = io.BytesIO()
        out.save(buf)
        return buf.getvalue()
