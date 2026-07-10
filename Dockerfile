# Backend container for the Doc2MD Converter API.
# Deployable to any container host (Render, Railway, Fly.io, a VPS…).
FROM python:3.11-slim

# Ghostscript powers high-quality PDF compression. Without it the API still
# works (it falls back to pikepdf), but image-heavy PDFs barely shrink.
RUN apt-get update \
    && apt-get install -y --no-install-recommends ghostscript \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python deps first so they cache across code changes.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Application code.
COPY main.py compression.py merging.py ./

# Bind all interfaces inside the container. Most hosts inject $PORT, which
# main.py reads; default to 8000 for local `docker run`.
ENV HOST=0.0.0.0 \
    PORT=8000
EXPOSE 8000

CMD ["python", "main.py"]
