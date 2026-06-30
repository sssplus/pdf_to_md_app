"""Document compression helpers for the Doc2MD service.

Two file types are supported:

* **PDF** — compressed with Ghostscript when the ``gs`` binary is available
  (best size reduction, can downsample images), falling back to a lossless
  ``pikepdf`` stream/object optimization when it is not.
* **DOCX** — re-zipped with maximum deflate compression, re-encoding any
  embedded raster images with Pillow.

Each function takes and returns raw bytes so callers never touch the filesystem
(Ghostscript is the one exception and uses a private temporary directory).
"""

from __future__ import annotations

import io
import logging
import shutil
import subprocess
import tempfile
import zipfile
from pathlib import Path

from PIL import Image

logger = logging.getLogger("doc2md.compression")

# Reject decompression-bomb images: cap the pixel count Pillow will decode.
# A tiny file can claim enormous dimensions and exhaust RAM on open; 50 MP is
# comfortably above any legitimate document image.
Image.MAX_IMAGE_PIXELS = 50_000_000

# Hard cap on the total *uncompressed* size of a DOCX archive. DOCX is a ZIP,
# so a small "zip bomb" can inflate to gigabytes; halt before that exhausts RAM.
_DOCX_MAX_UNCOMPRESSED_BYTES = 200 * 1024 * 1024  # 200 MB

# Ghostscript -dPDFSETTINGS presets, from smallest to largest output.
_GS_PRESETS = {
    "screen": "/screen",    # 72 dpi  — smallest, lowest quality
    "ebook": "/ebook",      # 150 dpi — good balance (default)
    "printer": "/printer",  # 300 dpi — high quality
}

# JPEG quality used when re-encoding images inside a DOCX, per preset.
_DOCX_JPEG_QUALITY = {"screen": 60, "ebook": 75, "printer": 85}

# Longest-edge cap (pixels) for downscaling oversized DOCX images.
_DOCX_IMAGE_MAX_EDGE = 1600

DEFAULT_QUALITY = "ebook"

# Ghostscript wall-clock budget. Free-tier hosts (e.g. Render) enforce their
# own hard proxy timeout (~100s) that the app cannot extend, so this must
# leave headroom for upload + response time within that window rather than
# the generous 120s used previously — a run that hits *that* timeout would
# already lose the race against the platform silently dropping the
# connection (the client sees a bare network error, never our response).
_GS_TIMEOUT_SECONDS = 75


class GhostscriptTimeout(Exception):
    """Raised when Ghostscript exceeds ``_GS_TIMEOUT_SECONDS`` on a PDF.

    Kept distinct from "Ghostscript unavailable/crashed" so the caller can
    report an honest timeout instead of silently swapping in the
    quality-blind pikepdf fallback, which would otherwise make the chosen
    ``quality`` look like it had no effect.
    """


def ghostscript_available() -> bool:
    """Return ``True`` if the Ghostscript ``gs`` binary is on PATH."""
    return shutil.which("gs") is not None


def compress_pdf(data: bytes, quality: str = DEFAULT_QUALITY) -> bytes:
    """Compress a PDF, preferring Ghostscript and falling back to pikepdf.

    Raises ``GhostscriptTimeout`` if Ghostscript exceeds its time budget —
    callers should report that as a timeout, not silently fall back.
    """
    if ghostscript_available():
        compressed = _compress_pdf_ghostscript(data, quality)
        if compressed is not None:
            return compressed
        logger.warning("Ghostscript failed; falling back to pikepdf.")
    return _compress_pdf_pikepdf(data)


def _compress_pdf_ghostscript(data: bytes, quality: str) -> bytes | None:
    """Compress with Ghostscript. Returns ``None`` if it is unavailable/fails."""
    preset = _GS_PRESETS.get(quality, _GS_PRESETS[DEFAULT_QUALITY])
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / "in.pdf"
        dst = Path(tmp) / "out.pdf"
        src.write_bytes(data)
        cmd = [
            "gs",
            "-dSAFER",  # sandbox: block arbitrary file read/write & shell escapes
            "-sDEVICE=pdfwrite",
            "-dCompatibilityLevel=1.4",
            f"-dPDFSETTINGS={preset}",
            "-dNOPAUSE",
            "-dBATCH",
            "-dQUIET",
            "-dDetectDuplicateImages=true",
            f"-sOutputFile={dst}",
            str(src),
        ]
        try:
            subprocess.run(cmd, check=True, timeout=_GS_TIMEOUT_SECONDS, capture_output=True)
        except subprocess.TimeoutExpired as exc:
            raise GhostscriptTimeout(
                f"Ghostscript exceeded the {_GS_TIMEOUT_SECONDS}s budget"
            ) from exc
        except (subprocess.SubprocessError, OSError) as exc:
            logger.warning("Ghostscript invocation failed: %s", exc)
            return None
        if dst.exists() and dst.stat().st_size > 0:
            return dst.read_bytes()
    return None


def _compress_pdf_pikepdf(data: bytes) -> bytes:
    """Losslessly optimize PDF streams and object structure with pikepdf."""
    import pikepdf

    out = io.BytesIO()
    with pikepdf.open(io.BytesIO(data)) as pdf:
        pdf.save(
            out,
            compress_streams=True,
            recompress_flate=True,
            object_stream_mode=pikepdf.ObjectStreamMode.generate,
        )
    return out.getvalue()


def compress_docx(data: bytes, quality: str = DEFAULT_QUALITY) -> bytes:
    """Re-zip a DOCX with max deflate and re-encode embedded raster images."""
    jpeg_quality = _DOCX_JPEG_QUALITY.get(quality, _DOCX_JPEG_QUALITY[DEFAULT_QUALITY])
    out_buf = io.BytesIO()

    total_uncompressed = 0
    with zipfile.ZipFile(io.BytesIO(data)) as src, zipfile.ZipFile(
        out_buf, "w", zipfile.ZIP_DEFLATED, compresslevel=9
    ) as out:
        for info in src.infolist():
            # Zip-bomb guard: stop before the cumulative uncompressed size of the
            # archive can exhaust memory. Checked before reading each member.
            total_uncompressed += info.file_size
            if total_uncompressed > _DOCX_MAX_UNCOMPRESSED_BYTES:
                raise ValueError(
                    "DOCX archive expands beyond the allowed size; refusing to process."
                )

            raw = src.read(info)
            if info.filename.startswith("word/media/"):
                raw = _recompress_image(raw, jpeg_quality) or raw
            out.writestr(info.filename, raw)

    return out_buf.getvalue()


def _recompress_image(raw: bytes, jpeg_quality: int) -> bytes | None:
    """Downscale and re-encode an image. Returns ``None`` to keep the original.

    Any failure (unsupported format, decode error, or a result no smaller than
    the input) leaves the original bytes untouched, so a single odd image can
    never corrupt the document.
    """
    try:
        image = Image.open(io.BytesIO(raw))
        fmt = (image.format or "").upper()
        if fmt not in ("JPEG", "PNG"):
            return None

        width, height = image.size
        scale = _DOCX_IMAGE_MAX_EDGE / max(width, height)
        if scale < 1:
            image = image.resize((round(width * scale), round(height * scale)), Image.LANCZOS)

        buf = io.BytesIO()
        if fmt == "JPEG":
            image.convert("RGB").save(buf, "JPEG", quality=jpeg_quality, optimize=True)
        else:
            image.save(buf, "PNG", optimize=True)

        compressed = buf.getvalue()
        return compressed if len(compressed) < len(raw) else None
    except Exception:  # noqa: BLE001 — never let one image break the document
        logger.debug("Skipping image that could not be recompressed", exc_info=True)
        return None
