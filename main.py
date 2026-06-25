"""Doc2MD Converter API.

A small FastAPI service that converts uploaded PDF, DOC, and DOCX files to
Markdown using Microsoft's `markitdown` library, and compresses PDF and DOCX
files.
"""

import logging
import os
import tempfile
from pathlib import Path

import uvicorn
from fastapi import FastAPI, File, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse, Response
from markitdown import MarkItDown

import compression

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("doc2md")

# Extensions accepted by /api/convert.
ALLOWED_EXTENSIONS = {".pdf", ".docx", ".doc"}

# Extensions accepted by /api/compress (the legacy binary .doc format cannot be
# meaningfully recompressed, so it is excluded).
COMPRESSIBLE_EXTENSIONS = {".pdf", ".docx"}

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
    description="Converts PDF, DOC, and DOCX files to Markdown using markitdown.",
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


async def _read_upload(file: UploadFile, allowed: set[str]) -> tuple[bytes, str]:
    """Validate an upload and return its bytes and lower-cased extension.

    Raises ``HTTPException`` for a missing/empty file, an unsupported
    extension, or content exceeding ``MAX_UPLOAD_BYTES``.
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

    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="The uploaded file is empty.")
    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"File is too large. Maximum size is "
            f"{MAX_UPLOAD_BYTES // (1024 * 1024)} MB.",
        )
    return content, extension


@app.get("/", tags=["meta"])
async def root():
    """Basic service metadata."""
    return {
        "service": "Doc2MD Converter API",
        "convert_endpoint": "/api/convert",
        "compress_endpoint": "/api/compress",
        "convert_extensions": sorted(ALLOWED_EXTENSIONS),
        "compress_extensions": sorted(COMPRESSIBLE_EXTENSIONS),
        "ghostscript": compression.ghostscript_available(),
    }


@app.get("/health", tags=["meta"])
async def health():
    """Liveness probe."""
    return {"status": "ok"}


@app.post("/api/convert", response_class=PlainTextResponse, tags=["convert"])
async def convert_document_to_markdown(file: UploadFile = File(...)):
    """Convert an uploaded PDF, DOC, or DOCX file to Markdown."""
    content, extension = await _read_upload(file, ALLOWED_EXTENSIONS)

    tmp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=extension) as tmp_file:
            tmp_file.write(content)
            tmp_path = Path(tmp_file.name)

        result = _converter.convert(str(tmp_path))
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
        if extension == ".pdf":
            compressed = compression.compress_pdf(content, quality)
            media_type = "application/pdf"
        else:  # .docx
            compressed = compression.compress_docx(content, quality)
            media_type = _DOCX_MEDIA_TYPE
    except Exception:
        logger.exception("Failed to compress %s", file.filename)
        raise HTTPException(
            status_code=500,
            detail="Failed to compress the document. The file may be corrupt or unsupported.",
        )

    # Never return a larger file than we received.
    if len(compressed) >= len(content):
        compressed = content

    stem = Path(file.filename).stem
    download_name = f"{stem}-compressed{extension}"
    return Response(
        content=compressed,
        media_type=media_type,
        headers={
            "Content-Disposition": f'attachment; filename="{download_name}"',
            "X-Original-Size": str(len(content)),
            "X-Compressed-Size": str(len(compressed)),
        },
    )


if __name__ == "__main__":
    host = os.getenv("HOST", "127.0.0.1")
    port = int(os.getenv("PORT", "8000"))
    uvicorn.run(app, host=host, port=port)
