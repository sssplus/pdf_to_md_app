# Changelog

All notable changes to Doc2MD are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- **Merge mode.** A third mode alongside *Convert* and *Compress*: select two
  or more PDFs, reorder or remove them in a queue, and merge them into a
  single downloadable PDF via the new `POST /api/merge` endpoint
  (`merging.py`, using `pikepdf`). Password-protected inputs are rejected
  with a distinct `422` error rather than a generic failure.

## [1.0.0] — 2026-06-30

The first stable release: a hardened, dual-purpose document tool — convert to
Markdown **or** compress — behind a new glassmorphic UI.

### Added

- **Compress mode.** Toggle between *Convert to Markdown* and *Compress File*
  (PDF and DOCX) with selectable quality (screen / ebook / printer) and a
  result card showing the size saved.
  - **PDF:** Ghostscript downsampling when available, with a hard DPI cap and
    CMYK→RGB conversion for consistent reduction; lossless pikepdf stream
    optimization as a fallback.
  - **DOCX:** repackaged with maximum Deflate compression and oversized
    embedded images downscaled/re-encoded with Pillow.
- **Glassmorphic UI:** Outfit font, an animated mesh-gradient backdrop,
  frosted-glass surfaces, and micro-animations (honours
  `prefers-reduced-motion`).
- **Backend deployment config:** `Dockerfile`, `.dockerignore`, and a Render
  `render.yaml` blueprint; GitHub Pages workflow for the frontend.
- **Security smoke-test CI** (`backend-ci.yml`) covering the hardening guards.

### Changed

- Frontend rewritten into a clean Vite + React structure (`src/`), fixing a
  broken entry path that previously prevented the app from building.
- Configurable API URL (`VITE_API_URL`), upload size limit, and CORS origins.
- Markdown preview is sanitized with DOMPurify before rendering.

### Security

- **Ghostscript sandbox:** PDF processing runs under `-dSAFER` to block
  arbitrary file access and reduce RCE risk from crafted PDFs.
- **Zip-bomb guard:** aborts DOCX processing above a 200 MB uncompressed cap.
- **Decompression-bomb guard:** `Image.MAX_IMAGE_PIXELS` caps the pixels Pillow
  will decode, rejecting malicious images.
- **Header-injection fix:** download filenames are sanitized per RFC 6266
  (`filename*` percent-encoding plus an ASCII fallback).
- Exceptions are logged server-side without leaking internals to clients.

### Notes

- Supported formats are **PDF and DOCX**. The legacy binary `.doc` format is not
  supported (it is rejected with HTTP 415).
- "Lossless" applies to the pikepdf PDF path; the Ghostscript and image
  downsampling paths are intentionally lossy to reduce size.

[1.0.0]: https://github.com/sssplus/pdf_to_md_app/releases/tag/v1.0.0
