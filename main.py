"""Doc2MD Converter API.

A small FastAPI service that converts uploaded PDF and DOCX files to
Markdown using Microsoft's `markitdown` library, and compresses PDF and DOCX
files.
"""

import logging
import os
import re
import tempfile
from pathlib import Path
from urllib.parse import quote

import uvicorn
from fastapi import FastAPI, File, HTTPException, Query, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse, Response
from markitdown import MarkItDown

import compression
import merging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("doc2md")

# Extensions accepted by /api/convert. Legacy binary .doc is intentionally
# excluded: the installed markitdown[pdf,docx] extras register no converter
# for it (only modern OOXML .docx), so every .doc upload would otherwise
# pass validation and then always fail conversion with an opaque 500.
ALLOWED_EXTENSIONS = {".pdf", ".docx"}

# Extensions accepted by /api/compress (the legacy binary .doc format cannot be
# meaningfully recompressed, so it is excluded).
COMPRESSIBLE_EXTENSIONS = {".pdf", ".docx"}

# Extensions accepted by /api/merge — PDF only.
MERGEABLE_EXTENSIONS = {".pdf"}

_DOCX_MEDIA_TYPE = (
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
)

# Maximum upload size in bytes (default 25 MB), configurable via MAX_UPLOAD_MB.
MAX_UPLOAD_BYTES = int(os.getenv("MAX_UPLOAD_MB", "25")) * 1024 * 1024

# CORS origins, comma-separated, configurable via ALLOWED_ORIGINS.
ALLOWED_ORIGINS = [
    origin.strip()
    for origin in os.getenv(
        "ALLOWED_ORIGINS",
        "http://localhost:5173,http://127.0.0.1:5173",
    ).split(",")
    if origin.strip()
]

app = FastAPI(
    title="Doc2MD Converter API",
    description="Converts PDF and DOCX files to Markdown using markitdown.",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=False,
    allow_methods=["POST", "GET"],
    allow_headers=["*"],
    # Let the browser read the compression metadata returned by /api/compress.
    expose_headers=["Content-Disposition", "X-Original-Size", "X-Compressed-Size"],
)

# A single reusable converter instance.
_converter = MarkItDown()


def _content_disposition(download_name: str) -> str:
    """Build a safe ``Content-Disposition`` value for an attachment.

    Guards against HTTP header/response injection: the raw name may contain
    quotes or CR/LF. We emit a regex-sanitized ASCII ``filename`` plus a
    percent-encoded RFC 6266 ``filename*`` for full-fidelity Unicode names.
    """
    ascii_fallback = re.sub(r"[^A-Za-z0-9._-]", "_", download_name) or "document"
    encoded_name = quote(download_name, safe="")
    return f"attachment; filename=\"{ascii_fallback}\"; filename*=UTF-8''{encoded_name}"


# Chunk size for streaming an upload off the wire. Bounds peak memory to
# roughly MAX_UPLOAD_BYTES (the check below aborts as soon as the running
# total crosses it) instead of buffering an unbounded body in full first.
_UPLOAD_READ_CHUNK_BYTES = 1024 * 1024  # 1 MB


async def _read_upload(file: UploadFile, allowed: set[str]) -> tuple[bytes, str]:
    """Validate an upload and return its bytes and lower-cased extension.

    Raises ``HTTPException`` for a missing/empty file, an unsupported
    extension, or content exceeding ``MAX_UPLOAD_BYTES``. Reads the body in
    bounded chunks so an oversized upload is rejected as soon as it crosses
    the limit rather than being fully materialized in memory first.
    """
    if not file.filename:
        raise HTTPException(status_code=400, detail="No file was uploaded.")

    extension = Path(file.filename).suffix.lower()
    if extension not in allowed:
        raise HTTPException(
            status_code=415,
            detail=f"Unsupported file type '{extension}'. "
            f"Allowed types: {', '.join(sorted(allowed))}.",
        )

    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = await file.read(_UPLOAD_READ_CHUNK_BYTES)
        if not chunk:
            break
        total += len(chunk)
        if total > MAX_UPLOAD_BYTES:
            raise HTTPException(
                status_code=413,
                detail=f"File is too large. Maximum size is "
                f"{MAX_UPLOAD_BYTES // (1024 * 1024)} MB.",
            )
        chunks.append(chunk)

    if not chunks:
        raise HTTPException(status_code=400, detail="The uploaded file is empty.")
    return b"".join(chunks), extension


@app.get("/", tags=["meta"])
async def root():
    """Basic service metadata."""
    return {
        "service": "Doc2MD Converter API",
        "convert_endpoint": "/api/convert",
        "compress_endpoint": "/api/compress",
        "merge_endpoint": "/api/merge",
        "convert_extensions": sorted(ALLOWED_EXTENSIONS),
        "compress_extensions": sorted(COMPRESSIBLE_EXTENSIONS),
        "merge_extensions": sorted(MERGEABLE_EXTENSIONS),
        "ghostscript": compression.ghostscript_available(),
    }


@app.get("/health", tags=["meta"])
async def health():
    """Liveness probe."""
    return {"status": "ok"}


@app.post("/api/convert", response_class=PlainTextResponse, tags=["convert"])
async def convert_document_to_markdown(file: UploadFile = File(...)):
    """Convert an uploaded PDF or DOCX file to Markdown."""
    content, extension = await _read_upload(file, ALLOWED_EXTENSIONS)

    tmp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=extension) as tmp_file:
            tmp_file.write(content)
            tmp_path = Path(tmp_file.name)

        # markitdown's convert() is a blocking, synchronous parse — run it off
        # the event loop so one slow/large document doesn't stall every other
        # in-flight request (including the /health liveness probe).
        result = await run_in_threadpool(_converter.convert, str(tmp_path))
        return PlainTextResponse(
            content=result.text_content, media_type="text/markdown"
        )
    except Exception:
        # Log the full error server-side, but don't leak internals to clients.
        logger.exception("Failed to convert %s", file.filename)
        raise HTTPException(
            status_code=500,
            detail="Failed to convert the document. The file may be corrupt or unsupported.",
        )
    finally:
        if tmp_path is not None:
            tmp_path.unlink(missing_ok=True)


@app.post("/api/compress", tags=["compress"])
async def compress_document(
    file: UploadFile = File(...),
    quality: str = Query(
        compression.DEFAULT_QUALITY,
        pattern="^(screen|ebook|printer)$",
        description="Compression strength: screen (smallest), ebook, or printer.",
    ),
):
    """Compress an uploaded PDF or DOCX file and return the smaller version.

    If compression cannot beat the original size, the original bytes are
    returned unchanged so the result is never larger than the input.
    """
    content, extension = await _read_upload(file, COMPRESSIBLE_EXTENSIONS)

    try:
        # Ghostscript/zipfile/Pillow are all blocking — run off the event loop
        # so one slow/large file doesn't stall every other in-flight request.
        if extension == ".pdf":
            compressed = await run_in_threadpool(compression.compress_pdf, content, quality)
            media_type = "application/pdf"
        else:  # .docx
            compressed = await run_in_threadpool(compression.compress_docx, content, quality)
            media_type = _DOCX_MEDIA_TYPE
    except (compression.GhostscriptTimeout, compression.DocxCompressionTimeout):
        logger.warning("Compression timed out for %s", file.filename)
        raise HTTPException(
            status_code=504,
            detail="Compression timed out for this file. Try a smaller file or "
            "the 'Smaller file' quality setting.",
        )
    except ValueError as exc:
        # Raised by the DOCX zip-bomb guard — a deliberate size-policy
        # rejection, not a corrupt/unsupported file, so it gets its own
        # actionable status instead of the generic 500 below.
        logger.warning("Rejected %s: %s", file.filename, exc)
        raise HTTPException(status_code=413, detail=str(exc))
    except Exception:
        logger.exception("Failed to compress %s", file.filename)
        raise HTTPException(
            status_code=500,
            detail="Failed to compress the document. The file may be corrupt or unsupported.",
        )

    # Never return a larger file than we received.
    if len(compressed) >= len(content):
        compressed = content

    # Build the download filename from user input safely. The raw filename can
    # contain quotes, CR/LF, etc. — interpolating it into a header would allow
    # HTTP header/response injection.
    stem = Path(file.filename).stem
    download_name = f"{stem}-compressed{extension}"
    return Response(
        content=compressed,
        media_type=media_type,
        headers={
            "Content-Disposition": _content_disposition(download_name),
            "X-Original-Size": str(len(content)),
            "X-Compressed-Size": str(len(compressed)),
        },
    )


@app.post("/api/merge", tags=["merge"])
async def merge_documents(files: list[UploadFile] = File(...)):
    """Merge two or more uploaded PDF files, in order, into one PDF."""
    if len(files) < merging.MIN_MERGE_FILES:
        raise HTTPException(
            status_code=400, detail="Select at least two PDF files to merge."
        )

    contents: list[bytes] = []
    for file in files:
        content, _extension = await _read_upload(file, MERGEABLE_EXTENSIONS)
        contents.append(content)

    try:
        merged = await run_in_threadpool(merging.merge_pdfs, contents)
    except merging.EncryptedPdfError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except Exception:
        logger.exception("Failed to merge %d PDFs", len(files))
        raise HTTPException(
            status_code=500,
            detail="Failed to merge the PDFs. One of the files may be corrupt or unsupported.",
        )

    return Response(
        content=merged,
        media_type="application/pdf",
        headers={"Content-Disposition": _content_disposition("merged.pdf")},
    )


if __name__ == "__main__":
    host = os.getenv("HOST", "127.0.0.1")
    port = int(os.getenv("PORT", "8000"))
    uvicorn.run(app, host=host, port=port)
