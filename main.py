"""Doc2MD Converter API.

A small FastAPI service that converts uploaded PDF, DOC, and DOCX files to
Markdown using Microsoft's `markitdown` library.
"""

import logging
import os
import tempfile
from pathlib import Path

import uvicorn
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse
from markitdown import MarkItDown

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("doc2md")

# Allowed upload extensions.
ALLOWED_EXTENSIONS = {".pdf", ".docx", ".doc"}

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
)

# A single reusable converter instance.
_converter = MarkItDown()


@app.get("/", tags=["meta"])
async def root():
    """Basic service metadata."""
    return {
        "service": "Doc2MD Converter API",
        "convert_endpoint": "/api/convert",
        "allowed_extensions": sorted(ALLOWED_EXTENSIONS),
    }


@app.get("/health", tags=["meta"])
async def health():
    """Liveness probe."""
    return {"status": "ok"}


@app.post("/api/convert", response_class=PlainTextResponse, tags=["convert"])
async def convert_document_to_markdown(file: UploadFile = File(...)):
    """Convert an uploaded PDF, DOC, or DOCX file to Markdown."""
    if not file.filename:
        raise HTTPException(status_code=400, detail="No file was uploaded.")

    extension = Path(file.filename).suffix.lower()
    if extension not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=415,
            detail=f"Unsupported file type '{extension}'. "
            f"Allowed types: {', '.join(sorted(ALLOWED_EXTENSIONS))}.",
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


if __name__ == "__main__":
    host = os.getenv("HOST", "127.0.0.1")
    port = int(os.getenv("PORT", "8000"))
    uvicorn.run(app, host=host, port=port)
