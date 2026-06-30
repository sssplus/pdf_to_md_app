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
import time
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

# Chunk size used to stream-decompress each zip entry. The cap above is
# enforced against bytes actually produced by decompression, not against
# ZipInfo.file_size -- that field comes from the (attacker-controlled) zip
# header and a crafted entry can declare a small size while its DEFLATE
# stream actually expands to hundreds of megabytes; zipfile only raises a
# CRC mismatch *after* fully decompressing such an entry, by which point the
# memory has already been allocated. Reading in bounded chunks lets us abort
# mid-stream instead.
_DOCX_READ_CHUNK_BYTES = 1024 * 1024  # 1 MB

# Wall-clock budget for compress_docx, analogous to _GS_TIMEOUT_SECONDS: a
# DOCX with many/large embedded images can keep Pillow busy (LANCZOS resize +
# optimize=True encode per image) well past a free-tier host's hard proxy
# timeout, which would otherwise silently drop the connection mid-request.
_DOCX_TIMEOUT_SECONDS = 75

# Ghostscript -dPDFSETTINGS presets, from smallest to largest output.
_GS_PRESETS = {
    "screen": "/screen",    # 72 dpi  — smallest, lowest quality
    "ebook": "/ebook",      # 150 dpi — good balance (default)
    "printer": "/printer",  # 300 dpi — high quality
}

# Target resolution (dpi) for colour/greyscale images, per quality. We set
# these *explicitly* rather than trusting the -dPDFSETTINGS preset, because a
# preset only supplies *defaults* and pairs them with a 1.5x downsample
# threshold — so an image merely below 1.5x the target (e.g. a 200 dpi scan
# under /ebook's 150 dpi target) is left completely untouched, which is the
# main reason results were inconsistent. Pinning the resolution and forcing
# the threshold to 1.0 (see _compress_pdf_ghostscript) makes any image above
# the target downsample, every time.
_GS_COLOR_DPI = {"screen": 72, "ebook": 150, "printer": 300}

# Bilevel (1-bit) images stay high: text/line-art scans compress extremely
# well at 1-bit and look terrible if downsampled to photo resolutions, so we
# don't drop these to 72/150.
_GS_MONO_DPI = {"screen": 300, "ebook": 300, "printer": 300}

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


class DocxCompressionTimeout(Exception):
    """Raised when ``compress_docx`` exceeds ``_DOCX_TIMEOUT_SECONDS``."""


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


def _gs_downsample_flags(quality: str) -> list[str]:
    """Explicit image-downsampling + colour flags that override the preset.

    These MUST appear *after* ``-dPDFSETTINGS`` on the command line so they win
    over the preset's defaults (Ghostscript is last-wins for repeated params).

    - Force downsampling on for all three image classes and pin the target
      resolution to the chosen quality, with a 1.0 threshold so *anything*
      above target is downsampled (the preset's 1.5x threshold let many
      images through unchanged).
    - Force CMYK → RGB so documents that accidentally carry heavy CMYK image
      data collapse to three channels. Greyscale is deliberately *not* forced;
      it is too visually destructive to apply blindly.
    """
    color_dpi = _GS_COLOR_DPI.get(quality, _GS_COLOR_DPI[DEFAULT_QUALITY])
    mono_dpi = _GS_MONO_DPI.get(quality, _GS_MONO_DPI[DEFAULT_QUALITY])
    return [
        "-dDownsampleColorImages=true",
        "-dDownsampleGrayImages=true",
        "-dDownsampleMonoImages=true",
        f"-dColorImageResolution={color_dpi}",
        f"-dGrayImageResolution={color_dpi}",
        f"-dMonoImageResolution={mono_dpi}",
        "-dColorImageDownsampleThreshold=1.0",
        "-dGrayImageDownsampleThreshold=1.0",
        "-dMonoImageDownsampleThreshold=1.0",
        "-dColorImageDownsampleType=/Bicubic",
        "-dGrayImageDownsampleType=/Bicubic",
        "-sColorConversionStrategy=RGB",
        "-dConvertCMYKImagesToRGB=true",
    ]


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
            # Override the preset's image defaults for consistent downsampling.
            *_gs_downsample_flags(quality),
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


def _read_entry_bounded(src: zipfile.ZipFile, info: zipfile.ZipInfo, budget: int) -> bytes:
    """Decompress one zip entry in chunks, aborting once it exceeds ``budget``.

    Never trusts ``info.file_size`` (attacker-controlled zip metadata) — the
    cap is enforced against bytes actually produced by decompression.
    """
    chunks = []
    total = 0
    with src.open(info) as fh:
        while True:
            chunk = fh.read(_DOCX_READ_CHUNK_BYTES)
            if not chunk:
                break
            total += len(chunk)
            if total > budget:
                raise ValueError(
                    "DOCX archive expands beyond the allowed size; refusing to process."
                )
            chunks.append(chunk)
    return b"".join(chunks)


def compress_docx(data: bytes, quality: str = DEFAULT_QUALITY) -> bytes:
    """Re-zip a DOCX with max deflate and re-encode embedded raster images."""
    jpeg_quality = _DOCX_JPEG_QUALITY.get(quality, _DOCX_JPEG_QUALITY[DEFAULT_QUALITY])
    out_buf = io.BytesIO()

    total_uncompressed = 0
    deadline = time.monotonic() + _DOCX_TIMEOUT_SECONDS
    with zipfile.ZipFile(io.BytesIO(data)) as src, zipfile.ZipFile(
        out_buf, "w", zipfile.ZIP_DEFLATED, compresslevel=9
    ) as out:
        for info in src.infolist():
            if time.monotonic() > deadline:
                raise DocxCompressionTimeout(
                    f"DOCX compression exceeded the {_DOCX_TIMEOUT_SECONDS}s budget"
                )

            # Zip-bomb guard: bound the cumulative *actual* decompressed size,
            # not the declared one, before it can exhaust memory.
            raw = _read_entry_bounded(src, info, _DOCX_MAX_UNCOMPRESSED_BYTES - total_uncompressed)
            total_uncompressed += len(raw)

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
