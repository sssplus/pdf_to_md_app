import uvicorn
from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.responses import PlainTextResponse
from fastapi.middleware.cors import CORSMiddleware
import tempfile
import os
from pathlib import Path
from markitdown import MarkItDown

app = FastAPI(
    title="Doc2MD Converter API",
    description="Converts PDF and DOCX files to Markdown using markitdown.",
    version="1.0.0"
)

# CORS configuration for frontend
origins = [
    "http://localhost:5173",  # React Vite default port
    "http://127.0.0.1:5173",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.post("/api/convert")
async def convert_document_to_markdown(file: UploadFile = File(...)):
    """
    Converts an uploaded PDF or DOCX file to Markdown.
    """
    if not file.filename:
        raise HTTPException(status_code=400, detail="No file uploaded.")

    file_extension = Path(file.filename).suffix.lower()

    if file_extension not in [".pdf", ".docx", ".doc"]:
        raise HTTPException(
            status_code=400,
            detail="Unsupported file type. Only .pdf and .doc(x) are allowed."
        )

    # Use a temporary file to save the uploaded content
    with tempfile.NamedTemporaryFile(delete=False, suffix=file_extension) as tmp_file:
        content = await file.read()
        tmp_file.write(content)
        tmp_path = Path(tmp_file.name)

    markdown_output = ""
    try:
        md = MarkItDown()
        result = md.convert(str(tmp_path))
        markdown_output = result.text_content
    except Exception as e:
        # Log the error for debugging
        print(f"Error during conversion of {file.filename}: {e}")
        raise HTTPException(status_code=500, detail=f"Conversion failed: {e}")
    finally:
        # Clean up the temporary file
        try:
            os.unlink(tmp_path)
        except Exception:
            pass

    return PlainTextResponse(content=markdown_output, media_type="text/markdown")

@app.get("/")
async def root():
    return {"message": "Welcome to the Doc2MD Converter API. Use /api/convert to upload files."}

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
