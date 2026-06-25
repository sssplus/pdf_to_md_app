# Doc2MD

> Convert **PDF / DOC / DOCX** to clean **Markdown**, or **compress** PDF and
> Word files — drag, drop, done.

Doc2MD is a small full-stack app with a React frontend and a FastAPI backend. It
uses Microsoft's [`markitdown`](https://github.com/microsoft/markitdown) library
to turn documents into Markdown (live preview, raw view, copy, download), and
shrinks PDF/DOCX files with Ghostscript and Pillow.

![License: GPL v3](https://img.shields.io/badge/License-GPLv3-blue.svg)

## Features

- 🗂️ **Drag & drop** upload (PDF, DOC, DOCX)
- 🔄 **Convert** documents to Markdown — **live preview** + **raw** view
- 🗜️ **Compress** PDF and DOCX files with selectable quality, showing how much
  smaller the result is
- 📋 **Copy to clipboard** and 💾 **download** results
- 🔒 Sanitized HTML preview (DOMPurify) — safe rendering of untrusted documents
- 🧹 Files are processed in memory / a temp file and **never stored**
- ⚙️ Configurable API URL, upload size limit, and CORS origins

## Tech stack

| Layer    | Tools                                                       |
| -------- | ----------------------------------------------------------- |
| Frontend | React 18, Vite, react-dropzone, marked, DOMPurify           |
| Backend  | FastAPI, Uvicorn, markitdown, pikepdf, Pillow, Ghostscript* |

\* Ghostscript is an **optional** system binary. When present it is used for
PDF compression (best results); otherwise the backend falls back to `pikepdf`.

## Getting started

### Prerequisites

- [Node.js](https://nodejs.org/) 18+
- [Python](https://www.python.org/) 3.10+
- _(optional)_ [Ghostscript](https://www.ghostscript.com/) for best PDF
  compression — `apt-get install ghostscript` (Debian/Ubuntu),
  `brew install ghostscript` (macOS). Without it, PDF compression falls back to
  `pikepdf`.

### 1. Backend

```bash
# (optional) create a virtual environment
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate

pip install -r requirements.txt
python main.py                   # serves http://127.0.0.1:8000
```

### 2. Frontend

```bash
npm install
cp .env.example .env             # adjust VITE_API_URL if your backend isn't on :8000
npm run dev                      # serves http://localhost:5173
```

Open <http://localhost:5173>, drop in a document, and watch it convert.

## Configuration

### Frontend (`.env`)

| Variable       | Default                 | Description                  |
| -------------- | ----------------------- | ---------------------------- |
| `VITE_API_URL` | `http://localhost:8000` | Base URL of the backend API. |

### Backend (environment variables)

| Variable          | Default                                              | Description                                  |
| ----------------- | ---------------------------------------------------- | -------------------------------------------- |
| `HOST`            | `127.0.0.1`                                          | Interface to bind to.                        |
| `PORT`            | `8000`                                               | Port to listen on.                           |
| `MAX_UPLOAD_MB`   | `25`                                                 | Maximum upload size in megabytes.            |
| `ALLOWED_ORIGINS` | `http://localhost:5173,http://127.0.0.1:5173`        | Comma-separated CORS origins.                |

## API

### `POST /api/convert`

Multipart form upload with a single `file` field (`.pdf`, `.doc`, `.docx`).
Returns the converted Markdown as `text/markdown`.

```bash
curl -F "file=@document.pdf" http://localhost:8000/api/convert
```

### `POST /api/compress`

Multipart form upload with a single `file` field (`.pdf` or `.docx`). Optional
`quality` query parameter: `screen` (smallest), `ebook` (default), or
`printer` (highest quality). Returns the compressed file as a binary download,
with `X-Original-Size` and `X-Compressed-Size` response headers. If compression
can't beat the original, the original bytes are returned unchanged.

```bash
curl -F "file=@document.pdf" \
  "http://localhost:8000/api/compress?quality=ebook" -o document-compressed.pdf
```

Error responses are JSON with a `detail` message and an appropriate status code
(`400`, `413`, `415`, or `500`).

### `GET /health`

Returns `{"status": "ok"}` for liveness checks.

## Project structure

```
pdf_to_md_app/
├── main.py             # FastAPI backend (convert + compress endpoints)
├── compression.py      # PDF/DOCX compression helpers
├── requirements.txt    # Python dependencies
├── index.html          # Vite entry point
├── package.json
├── vite.config.js
├── eslint.config.js
├── .env.example
└── src/                # React frontend
    ├── main.jsx
    ├── App.jsx
    ├── App.css
    └── index.css
```

## Building for production

```bash
npm run build           # outputs static assets to dist/
npm run preview         # preview the production build locally
```

Serve `dist/` with any static host and point it at your deployed backend via
`VITE_API_URL` at build time.

## Contributing

Contributions are welcome! Please see [CONTRIBUTING.md](CONTRIBUTING.md).

## License

Licensed under the [GNU General Public License v3.0](LICENSE).
