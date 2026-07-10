# Doc2MD

> Convert **PDF / DOCX** to clean **Markdown**, **compress** PDF and
> Word files, or **merge** multiple PDFs — drag, drop, done.

Doc2MD is a small full-stack app with a React frontend and a FastAPI backend. It
uses Microsoft's [`markitdown`](https://github.com/microsoft/markitdown) library
to turn documents into Markdown (live preview, raw view, copy, download),
shrinks PDF/DOCX files with Ghostscript and Pillow, and merges PDFs with
`pikepdf`.

![License: GPL v3](https://img.shields.io/badge/License-GPLv3-blue.svg)

## Features

- 🗂️ **Drag & drop** upload (PDF, DOCX)
- 🔄 **Convert** documents to Markdown — **live preview** + **raw** view
- 🗜️ **Compress** PDF and DOCX files with selectable quality, showing how much
  smaller the result is
- 📎 **Merge** two or more PDFs into one, with drag-and-drop queueing,
  reordering, and removal before merging
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
PDF merging always uses `pikepdf`.

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

Multipart form upload with a single `file` field (`.pdf`, `.docx`).
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

### `POST /api/merge`

Multipart form upload with two or more `files` fields, each a `.pdf`. Merges
them, in the order given, into a single PDF and returns it as a binary
download named `merged.pdf`.

```bash
curl -F "files=@first.pdf" -F "files=@second.pdf" \
  http://localhost:8000/api/merge -o merged.pdf
```

Error responses are JSON with a `detail` message: `400` for fewer than two
files, `415` for a non-PDF upload, and `422` if one of the PDFs is
password-protected.

### `GET /health`

Returns `{"status": "ok"}` for liveness checks.

## Project structure

```
pdf_to_md_app/
├── main.py             # FastAPI backend (convert + compress + merge endpoints)
├── compression.py      # PDF/DOCX compression helpers
├── merging.py          # PDF merging helpers
├── requirements.txt    # Python dependencies
├── Dockerfile          # Backend container image
├── render.yaml         # Render.com deployment blueprint
├── index.html          # Vite entry point
├── package.json
├── vite.config.js
├── eslint.config.js
├── .env.example
├── .github/workflows/  # CI: GitHub Pages deploy
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

## Deployment

GitHub can't host the Python backend (Pages serves static files only), so the
two halves deploy separately: **frontend → GitHub Pages**, **backend → any
container host**. Deploy the backend first so you have its URL for the frontend
build.

### 1. Backend → a container host

The included [`Dockerfile`](Dockerfile) runs the API (with Ghostscript) on any
Docker host. Locally:

```bash
docker build -t doc2md-api .
docker run -p 8000:8000 -e ALLOWED_ORIGINS=https://<user>.github.io doc2md-api
```

On [Render](https://render.com): **New → Blueprint** and point it at this repo —
[`render.yaml`](render.yaml) provisions a Docker web service with a `/health`
check. (Railway and Fly.io auto-detect the `Dockerfile` too.) Set
**`ALLOWED_ORIGINS`** to your GitHub Pages origin (e.g.
`https://<user>.github.io`, origin only — no path). Note the service URL, e.g.
`https://doc2md-api.onrender.com`.

### 2. Frontend → GitHub Pages

The [`deploy-pages.yml`](.github/workflows/deploy-pages.yml) workflow builds and
publishes `src/` on every push to `main`. One-time setup:

1. **Settings → Secrets and variables → Actions → Variables** → add
   **`VITE_API_URL`** = your backend URL from step 1.
2. **Settings → Pages → Source** → **GitHub Actions**.
3. Push to `main` (or run the workflow manually).

The app goes live at `https://<user>.github.io/pdf_to_md_app/`. If you use a
custom domain or a `<user>.github.io` user-site repo, change `VITE_BASE` in the
workflow from `/pdf_to_md_app/` to `/`.

## Contributing

Contributions are welcome! Please see [CONTRIBUTING.md](CONTRIBUTING.md).

## License

Licensed under the [GNU General Public License v3.0](LICENSE).
