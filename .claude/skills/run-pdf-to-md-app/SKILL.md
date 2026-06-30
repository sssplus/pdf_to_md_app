---
name: run-pdf-to-md-app
description: Build, launch, and drive the Doc2MD app (pdf_to_md_app) — a React + FastAPI tool that converts PDF/DOCX files to Markdown and compresses PDF/DOCX files. Use when asked to run, start, serve, build, smoke-test, screenshot, or verify the Doc2MD converter/compressor, its frontend, or its backend API.
---

# Run Doc2MD (pdf_to_md_app)

Doc2MD is a two-process web app:

- **Backend** — FastAPI (`main.py`) exposing `POST /api/convert` (markitdown →
  Markdown) and `POST /api/compress` (PDF/DOCX size reduction via
  `compression.py`). Drive it with **`curl`**.
- **Frontend** — React + Vite (`src/`) with a Convert/Compress mode toggle that
  posts to the backend. Drive it headless with the committed Playwright driver
  **`.claude/skills/run-pdf-to-md-app/driver.mjs`**.

All paths below are relative to the repo root (`pdf_to_md_app/`). All commands
here were run in the Claude web container and worked.

## Prerequisites

```bash
# Python deps. markitdown pulls in numpy + onnxruntime, so this is a big install.
pip install -r requirements.txt

# The container ships a broken debian `cryptography` (missing _cffi_backend),
# which pdfminer imports. Force-replace it with pip wheels, or the backend
# crashes on startup with PanicException / ModuleNotFoundError: _cffi_backend.
pip install --upgrade --ignore-installed cffi cryptography

# Frontend deps.
npm install

# Optional: Ghostscript gives much better PDF compression. Without it the
# backend falls back to pikepdf (lossless, modest savings). The /api/compress
# endpoint works either way.
apt-get install -y ghostscript
```

Node 18+ and Python 3.10+ are required (verified on Node 22, Python 3.11).
`requirements.txt` already includes `pikepdf` and `Pillow` for compression.

## Run the backend (curl path)

```bash
PORT=8000 HOST=127.0.0.1 python3 main.py > /tmp/doc2md-backend.log 2>&1 &
echo $! > /tmp/doc2md-backend.pid
# Wait until it answers, then verify.
timeout 40 bash -c 'until curl -sf http://127.0.0.1:8000/health >/dev/null; do sleep 1; done'
curl -s http://127.0.0.1:8000/health        # -> {"status":"ok"}
```

Smoke-test the core conversion with the committed sample doc. This is the whole
point of the app — a document in, Markdown out:

```bash
curl -s -F "file=@.claude/skills/run-pdf-to-md-app/sample.docx" \
  http://127.0.0.1:8000/api/convert
# -> "# Sample Report\n\nThis is a sample document...\n\n## Key Points\n..."

# Rejection path: unsupported type returns 415 with a JSON detail.
echo hi > /tmp/note.txt
curl -s -o /dev/null -w "%{http_code}\n" -F "file=@/tmp/note.txt" \
  http://127.0.0.1:8000/api/convert      # -> 415
```

Smoke-test compression. The committed `sample.docx` has no images so it barely
shrinks; the size headers prove the endpoint round-trips a valid file:

```bash
curl -s -D - -o /tmp/out.docx \
  -F "file=@.claude/skills/run-pdf-to-md-app/sample.docx" \
  "http://127.0.0.1:8000/api/compress?quality=ebook" \
  | grep -i x-compressed-size      # -> x-compressed-size: <bytes>

# .doc is rejected by compress (only .pdf/.docx); invalid quality -> 422.
cp .claude/skills/run-pdf-to-md-app/sample.docx /tmp/fake.doc
curl -s -o /dev/null -w "%{http_code}\n" -F "file=@/tmp/fake.doc" \
  http://127.0.0.1:8000/api/compress   # -> 415
```

To see real savings, build an image-heavy fixture (see "Regenerating fixtures"
below) — an image-heavy DOCX compresses ~85%, and a photo PDF ~86% **with
Ghostscript installed** (pikepdf-only will return the original for already-JPEG
PDFs).

Stop it with `kill $(cat /tmp/doc2md-backend.pid)`.

## Run the frontend + drive it (browser path)

The frontend needs the backend running (it POSTs to `http://localhost:8000` by
default; override with `VITE_API_URL`). Start the dev server and wait for it:

```bash
npm run dev > /tmp/doc2md-frontend.log 2>&1 &
echo $! > /tmp/doc2md-frontend.pid
timeout 30 bash -c 'until curl -sf http://localhost:5173 >/dev/null; do sleep 1; done'
```

Then drive the full UI flow (upload → convert → toggle Preview/Raw → screenshot)
with the committed driver. It uploads a file, waits for the Download button to
appear (success), checks the rendered DOM, and writes screenshots:

```bash
# Convert flow (default mode):
node .claude/skills/run-pdf-to-md-app/driver.mjs \
  .claude/skills/run-pdf-to-md-app/sample.docx /tmp/doc2md-shots convert
# -> screenshots /tmp/doc2md-shots/{1-landing,2-preview,3-raw}.png

# Compress flow (3rd arg = "compress"): switches to Compress mode, uploads,
# and screenshots the size-savings result card.
node .claude/skills/run-pdf-to-md-app/driver.mjs \
  /tmp/imgheavy.docx /tmp/doc2md-shots compress
# -> screenshot /tmp/doc2md-shots/2-compress.png ("85% smaller", sizes)

# Both print "DRIVER OK" and "no console errors" on success.
```

**Look at `/tmp/doc2md-shots/2-preview.png`** (convert) — the `sample.md` card
with rendered headings — and `2-compress.png` (compress) — the result card with
a "% smaller" figure and original→compressed sizes. Pass any
`.pdf`/`.docx` (convert or compress) as the first arg.

Stop the dev server with `kill $(cat /tmp/doc2md-frontend.pid)`.

### Regenerating the sample fixture

`sample.docx` is a committed, hand-built minimal DOCX (no `python-docx` needed).
To rebuild it:

```bash
python3 - <<'PY'
import zipfile
ct='<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/></Types>'
rels='<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/></Relationships>'
def p(t,s=None):
    pr=f'<w:pPr><w:pStyle w:val="{s}"/></w:pPr>' if s else ''
    return f'<w:p>{pr}<w:r><w:t xml:space="preserve">{t}</w:t></w:r></w:p>'
doc=f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>{p("Sample Report","Heading1")}{p("This is a sample document used to verify the Doc2MD converter.")}{p("Key Points","Heading2")}{p("Doc2MD turns documents into Markdown.")}{p("It supports PDF, DOC, and DOCX files.")}</w:body></w:document>'
with zipfile.ZipFile(".claude/skills/run-pdf-to-md-app/sample.docx","w",zipfile.ZIP_DEFLATED) as z:
    z.writestr("[Content_Types].xml",ct); z.writestr("_rels/.rels",rels); z.writestr("word/document.xml",doc)
print("wrote sample.docx")
PY
```

To build the **image-heavy fixtures** used by the compression smoke tests
(`/tmp/imgheavy.docx` ~3 MB DOCX and `/tmp/photo.pdf` ~1.3 MB PDF), which is not
committed because of its size:

```bash
python3 - <<'PY'
import io, random, zipfile
from PIL import Image
random.seed(1)
W,H=2400,1800
img=Image.new("RGB",(W,H))
px=img.load()
for y in range(H):
    for x in range(0,W,4):
        c=((x+y)%256,(x*2)%256,(y*3)%256)
        for dx in range(4):
            if x+dx<W: px[x+dx,y]=c
for _ in range(200000):
    px[random.randrange(W),random.randrange(H)]=(random.randrange(256),)*3
buf=io.BytesIO(); img.save(buf,"JPEG",quality=95); jpeg=buf.getvalue()
ct='<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Default Extension="jpeg" ContentType="image/jpeg"/><Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/></Types>'
rels='<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/></Relationships>'
doc='<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>Image heavy doc</w:t></w:r></w:p></w:body></w:document>'
with zipfile.ZipFile("/tmp/imgheavy.docx","w",zipfile.ZIP_DEFLATED) as z:
    z.writestr("[Content_Types].xml",ct); z.writestr("_rels/.rels",rels)
    z.writestr("word/document.xml",doc); z.writestr("word/media/image1.jpeg",jpeg)
img.save("/tmp/photo.pdf","PDF",resolution=300)
print("wrote /tmp/imgheavy.docx and /tmp/photo.pdf")
PY
```

## Human path

`python3 main.py` then `npm run dev`, and open <http://localhost:5173> in a real
browser. Useless headless — use the driver above instead.

## Test / lint / build

```bash
npm run lint     # ESLint flat config — passes clean
npm run build    # vite build -> dist/ ; should succeed
```

There is no automated test suite; the curl smoke + driver above are the
verification path.

## Gotchas

- **Broken system `cryptography`.** The debian-packaged `cryptography 41.0.7`
  in this container can't load `_cffi_backend`; pdfminer (a markitdown dep)
  imports it, so the backend dies at *import time* with a Rust
  `PanicException`. The fix is `pip install --upgrade --ignore-installed cffi
  cryptography` (plain `--upgrade` fails: "Cannot uninstall ... RECORD file not
  found" because it was installed by debian).
- **No `chromium-cli` in this container.** The driver instead resolves the
  **global** Playwright via `createRequire(npm root -g)` — the project's own
  `node_modules` does not depend on Playwright. Chromium comes from
  `$PLAYWRIGHT_BROWSERS_PATH` (`/opt/pw-browsers`); the driver launches with
  `--no-sandbox` (required as root).
- **Hidden file input.** The dropzone's `<input type=file>` is visually hidden,
  so the driver uses `setInputFiles('input[type=file]', ...)` rather than
  clicking. Success is signalled by the **Download button** appearing.
- **Backend binds `127.0.0.1` by default** (not `0.0.0.0`). Fine locally; set
  `HOST=0.0.0.0` if you need to reach it from outside the container.
- **CORS.** The backend only allows `localhost:5173` / `127.0.0.1:5173` by
  default. If you serve the frontend on another origin, set `ALLOWED_ORIGINS`
  (comma-separated) or the browser fetch is blocked.
- **`markitdown` install is large/slow** (numpy, onnxruntime, pillow — ~60 MB of
  wheels). Budget time on a cold container.
- **PDF compression depends on Ghostscript.** With `gs` on PATH the backend uses
  it (`-dPDFSETTINGS=/ebook` etc.) and shrinks image PDFs ~85%. Without it,
  `pikepdf` only does lossless stream optimization — for an already-JPEG PDF it
  can't beat the original, so `/api/compress` returns the **original** bytes
  unchanged (by design: the endpoint never returns a larger file). The root
  endpoint reports `"ghostscript": true/false` so you can tell which path is
  active.
- **DOCX compression is image re-encoding.** It re-zips at max deflate and
  re-encodes `word/media/*` raster images via Pillow (downscale to 1600px,
  JPEG quality per preset). A text-only DOCX barely changes; the savings come
  from images. Each image is wrapped in try/except, so a weird image is left
  untouched rather than corrupting the doc.

## Troubleshooting

- **Backend exits immediately, log shows `ModuleNotFoundError: _cffi_backend`
  or `pyo3_runtime.PanicException`** → run the cffi/cryptography reinstall above.
- **Driver: `Cannot find module 'playwright'`** → it's only installed globally;
  the driver already handles this via `npm root -g`. Confirm with
  `node -e "require(require('child_process').execSync('npm root -g').toString().trim()+'/playwright')"`.
- **Driver: navigation succeeds but Download never appears / `error.png`
  written** → the backend isn't up or CORS is blocking. Check
  `/tmp/doc2md-backend.log` and that `curl .../health` returns ok.
- **`EADDRINUSE`** on relaunch → a previous server is still running; kill it via
  the saved pid file (`kill $(cat /tmp/doc2md-backend.pid)` /
  `kill $(cat /tmp/doc2md-frontend.pid)`).
