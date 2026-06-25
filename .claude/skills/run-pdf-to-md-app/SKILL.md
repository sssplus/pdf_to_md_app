---
name: run-pdf-to-md-app
description: Build, launch, and drive the Doc2MD app (pdf_to_md_app) — a React + FastAPI tool that converts PDF/DOC/DOCX files to Markdown. Use when asked to run, start, serve, build, smoke-test, screenshot, or verify the Doc2MD converter, its frontend, or its backend API.
---

# Run Doc2MD (pdf_to_md_app)

Doc2MD is a two-process web app:

- **Backend** — FastAPI (`main.py`) exposing `POST /api/convert`, which runs
  uploaded files through `markitdown`. Drive it with **`curl`**.
- **Frontend** — React + Vite (`src/`) that posts to the backend. Drive it
  headless with the committed Playwright driver
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
```

Node 18+ and Python 3.10+ are required (verified on Node 22, Python 3.11).

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
node .claude/skills/run-pdf-to-md-app/driver.mjs \
  .claude/skills/run-pdf-to-md-app/sample.docx /tmp/doc2md-shots
# -> screenshots in /tmp/doc2md-shots/{1-landing,2-preview,3-raw}.png
# -> prints "DRIVER OK" and "no console errors" on success
```

**Look at `/tmp/doc2md-shots/2-preview.png`** — you should see the `sample.md`
preview card with rendered headings ("Sample Report", "Key Points"). To drive a
different document, pass any `.pdf`/`.doc`/`.docx` path as the first argument.

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
