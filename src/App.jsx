import { useCallback, useEffect, useMemo, useState } from 'react';
import { useDropzone } from 'react-dropzone';
import { marked } from 'marked';
import DOMPurify from 'dompurify';
import './App.css';

// Base URL of the backend API. Configurable at build time via VITE_API_URL.
const API_URL = (import.meta.env.VITE_API_URL ?? 'http://localhost:8000').replace(/\/$/, '');

// Accepted file types per mode. Legacy binary .doc is not supported by
// any mode: the backend's markitdown install has no converter for it.
const CONVERT_ACCEPT = {
  'application/pdf': ['.pdf'],
  'application/vnd.openxmlformats-officedocument.wordprocessingml.document': ['.docx'],
};
const COMPRESS_ACCEPT = {
  'application/pdf': ['.pdf'],
  'application/vnd.openxmlformats-officedocument.wordprocessingml.document': ['.docx'],
};
const MERGE_ACCEPT = {
  'application/pdf': ['.pdf'],
};

const QUALITY_OPTIONS = [
  { value: 'screen', label: 'Smaller file' },
  { value: 'ebook', label: 'Balanced' },
  { value: 'printer', label: 'Higher quality' },
];

function replaceExtension(name, suffix) {
  if (!name) return `document${suffix}`;
  const dot = name.lastIndexOf('.');
  return `${dot > 0 ? name.slice(0, dot) : name}${suffix}`;
}

function insertBeforeExtension(name, insert) {
  if (!name) return `document${insert}`;
  const dot = name.lastIndexOf('.');
  if (dot <= 0) return `${name}${insert}`;
  return `${name.slice(0, dot)}${insert}${name.slice(dot)}`;
}

function formatBytes(bytes) {
  if (!bytes) return '0 B';
  const units = ['B', 'KB', 'MB', 'GB'];
  const i = Math.floor(Math.log(bytes) / Math.log(1024));
  return `${(bytes / 1024 ** i).toFixed(i === 0 ? 0 : 1)} ${units[i]}`;
}

export default function App() {
  const [mode, setMode] = useState('convert'); // 'convert' | 'compress' | 'merge'
  const [file, setFile] = useState(null);
  const [isProcessing, setIsProcessing] = useState(false);
  const [error, setError] = useState('');

  // Convert state
  const [markdown, setMarkdown] = useState('');
  const [showRaw, setShowRaw] = useState(false);
  const [copied, setCopied] = useState(false);

  // Compress state
  const [quality, setQuality] = useState('ebook');
  const [compressed, setCompressed] = useState(null); // { url, name, originalSize, compressedSize }

  // Merge state
  const [mergeFiles, setMergeFiles] = useState([]); // File[], in merge order
  const [merged, setMerged] = useState(null); // { url, name, fileCount }

  const clearResults = useCallback(() => {
    setError('');
    setMarkdown('');
    setShowRaw(false);
    setCopied(false);
    setFile(null);
    setMergeFiles([]);
    setCompressed((prev) => {
      if (prev) URL.revokeObjectURL(prev.url);
      return null;
    });
    setMerged((prev) => {
      if (prev) URL.revokeObjectURL(prev.url);
      return null;
    });
  }, []);

  // Revoke any outstanding object URLs when the component unmounts.
  useEffect(() => () => {
    if (compressed) URL.revokeObjectURL(compressed.url);
  }, [compressed]);

  useEffect(() => () => {
    if (merged) URL.revokeObjectURL(merged.url);
  }, [merged]);

  const switchMode = useCallback((next) => {
    if (next === mode) return;
    clearResults();
    setMode(next);
  }, [mode, clearResults]);

  const convert = useCallback(async (selected) => {
    const formData = new FormData();
    formData.append('file', selected);
    const response = await fetch(`${API_URL}/api/convert`, { method: 'POST', body: formData });
    if (!response.ok) throw await errorFromResponse(response, 'Failed to convert the document.');
    // A 200 with an unexpected Content-Type (e.g. an HTML page from a proxy/
    // CDN/WAF in front of the API) is not real markdown — fail loudly instead
    // of rendering it as if it were.
    const contentType = response.headers.get('Content-Type') || '';
    if (!contentType.includes('text/markdown') && !contentType.includes('text/plain')) {
      throw new Error('The server returned an unexpected response. Please try again.');
    }
    setMarkdown(await response.text());
  }, []);

  const compress = useCallback(async (selected) => {
    const formData = new FormData();
    formData.append('file', selected);
    const response = await fetch(
      `${API_URL}/api/compress?quality=${encodeURIComponent(quality)}`,
      { method: 'POST', body: formData },
    );
    if (!response.ok) throw await errorFromResponse(response, 'Failed to compress the document.');

    const blob = await response.blob();
    const originalSize = Number(response.headers.get('X-Original-Size')) || selected.size;
    const compressedSize = Number(response.headers.get('X-Compressed-Size')) || blob.size;
    setCompressed({
      url: URL.createObjectURL(blob),
      name: insertBeforeExtension(selected.name, '-compressed'),
      originalSize,
      compressedSize,
    });
  }, [quality]);

  const addMergeFiles = useCallback((selected, fileRejections) => {
    setMerged((prev) => {
      if (prev) URL.revokeObjectURL(prev.url);
      return null;
    });
    if (fileRejections.length > 0) {
      setError('Unsupported file type. Please upload PDF files only.');
    } else {
      setError('');
    }
    if (selected.length > 0) {
      setMergeFiles((prev) => [...prev, ...selected]);
    }
  }, []);

  const removeMergeFile = useCallback((index) => {
    setMergeFiles((prev) => prev.filter((_, i) => i !== index));
  }, []);

  const moveMergeFile = useCallback((index, direction) => {
    setMergeFiles((prev) => {
      const target = index + direction;
      if (target < 0 || target >= prev.length) return prev;
      const next = [...prev];
      [next[index], next[target]] = [next[target], next[index]];
      return next;
    });
  }, []);

  const handleMerge = useCallback(async () => {
    if (mergeFiles.length < 2) return;
    setError('');
    setIsProcessing(true);
    try {
      const formData = new FormData();
      mergeFiles.forEach((f) => formData.append('files', f));
      const response = await fetch(`${API_URL}/api/merge`, { method: 'POST', body: formData });
      if (!response.ok) throw await errorFromResponse(response, 'Failed to merge the PDFs.');
      const blob = await response.blob();
      setMerged({ url: URL.createObjectURL(blob), name: 'merged.pdf', fileCount: mergeFiles.length });
    } catch (err) {
      setError(err instanceof TypeError
        ? 'Could not reach the server. Is the backend running?'
        : err.message);
    } finally {
      setIsProcessing(false);
    }
  }, [mergeFiles]);

  const onDrop = useCallback(async (acceptedFiles, fileRejections) => {
    if (mode === 'merge') {
      addMergeFiles(acceptedFiles, fileRejections);
      return;
    }

    clearResults();
    if (fileRejections.length > 0) {
      setError('Unsupported file type. Please upload a PDF or DOCX file.');
      return;
    }
    if (acceptedFiles.length === 0) return;

    const selected = acceptedFiles[0];
    setFile(selected);
    setIsProcessing(true);
    try {
      if (mode === 'compress') await compress(selected);
      else await convert(selected);
    } catch (err) {
      setError(err instanceof TypeError
        ? 'Could not reach the server. Is the backend running?'
        : err.message);
    } finally {
      setIsProcessing(false);
    }
  }, [mode, clearResults, compress, convert, addMergeFiles]);

  const { getRootProps, getInputProps, isDragActive } = useDropzone({
    onDrop,
    accept: mode === 'compress' ? COMPRESS_ACCEPT : mode === 'merge' ? MERGE_ACCEPT : CONVERT_ACCEPT,
    multiple: mode === 'merge',
    disabled: isProcessing,
  });

  const renderedHtml = useMemo(
    () => (markdown ? DOMPurify.sanitize(marked.parse(markdown)) : ''),
    [markdown],
  );

  const handleCopy = useCallback(async () => {
    try {
      await navigator.clipboard.writeText(markdown);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      setError('Could not copy to clipboard.');
    }
  }, [markdown]);

  const handleDownloadMarkdown = useCallback(() => {
    const blob = new Blob([markdown], { type: 'text/markdown;charset=utf-8' });
    triggerDownload(URL.createObjectURL(blob), replaceExtension(file?.name, '.md'), true);
  }, [markdown, file]);

  const handleDownloadCompressed = useCallback(() => {
    if (compressed) triggerDownload(compressed.url, compressed.name, false);
  }, [compressed]);

  const savings = compressed && compressed.originalSize > 0
    ? Math.round((1 - compressed.compressedSize / compressed.originalSize) * 100)
    : 0;

  const supportedHint = mode === 'merge' ? '.pdf (select two or more)' : '.pdf, .docx';

  return (
    <div className="app">
      <header className="app-header">
        <h1>Doc2MD</h1>
        <p className="tagline">Convert documents to Markdown, shrink PDF and Word files, or merge PDFs.</p>
      </header>

      <main className="app-main">
        <div className="mode-switch" role="tablist" aria-label="Mode">
          {[
            ['convert', 'Convert to Markdown'],
            ['compress', 'Compress file'],
            ['merge', 'Merge PDFs'],
          ].map(([value, label]) => (
            <button
              key={value}
              type="button"
              role="tab"
              aria-selected={mode === value}
              className={mode === value ? 'active' : ''}
              onClick={() => switchMode(value)}
            >
              {label}
            </button>
          ))}
        </div>

        {mode === 'compress' && (
          <label className="quality-row">
            <span>Quality</span>
            <select value={quality} onChange={(e) => setQuality(e.target.value)} disabled={isProcessing}>
              {QUALITY_OPTIONS.map((o) => (
                <option key={o.value} value={o.value}>{o.label}</option>
              ))}
            </select>
          </label>
        )}

        <div
          {...getRootProps()}
          className={`dropzone ${isDragActive ? 'active' : ''} ${isProcessing ? 'disabled' : ''}`}
          aria-label="File upload area"
        >
          <input {...getInputProps()} />
          <svg className="dropzone-icon" viewBox="0 0 24 24" aria-hidden="true">
            <path d="M12 16V4m0 0l-4 4m4-4l4 4M4 16v2a2 2 0 002 2h12a2 2 0 002-2v-2" />
          </svg>
          {isDragActive ? (
            <p>
              Drop the file{mode === 'merge' ? 's' : ''} to{' '}
              {mode === 'compress' ? 'compress' : mode === 'merge' ? 'add' : 'convert'} it…
            </p>
          ) : mode === 'merge' ? (
            <p>
              <strong>Drag &amp; drop</strong> PDF files here,
              <br />
              or click to browse
            </p>
          ) : (
            <p>
              <strong>Drag &amp; drop</strong> a PDF or Word document here,
              <br />
              or click to browse
            </p>
          )}
          <span className="dropzone-hint">Supported: {supportedHint}</span>
        </div>

        {isProcessing && (
          <div className="status" role="status">
            <div className="loader" aria-hidden="true" />
            <span>
              {mode === 'compress' && `Compressing ${file?.name}…`}
              {mode === 'convert' && `Converting ${file?.name}…`}
              {mode === 'merge' && `Merging ${mergeFiles.length} files…`}
            </span>
          </div>
        )}

        {error && <div className="error-message" role="alert">{error}</div>}

        {/* Convert result */}
        {markdown && !isProcessing && (
          <section className="preview-container" aria-label="Conversion result">
            <div className="preview-header">
              <div className="preview-title">
                <h2>{replaceExtension(file?.name, '.md')}</h2>
                {file && <span className="file-meta">{formatBytes(file.size)}</span>}
              </div>
              <div className="preview-actions">
                <div className="toggle" role="tablist" aria-label="View mode">
                  <button type="button" role="tab" aria-selected={!showRaw}
                    className={!showRaw ? 'active' : ''} onClick={() => setShowRaw(false)}>Preview</button>
                  <button type="button" role="tab" aria-selected={showRaw}
                    className={showRaw ? 'active' : ''} onClick={() => setShowRaw(true)}>Raw</button>
                </div>
                <button type="button" className="btn" onClick={handleCopy}>{copied ? 'Copied!' : 'Copy'}</button>
                <button type="button" className="btn btn-primary" onClick={handleDownloadMarkdown}>Download</button>
                <button type="button" className="btn btn-ghost" onClick={clearResults}>Clear</button>
              </div>
            </div>
            {showRaw ? (
              <pre className="markdown-raw">{markdown}</pre>
            ) : (
              // Rendered by marked, then sanitized by DOMPurify above.
              <div className="markdown-body" dangerouslySetInnerHTML={{ __html: renderedHtml }} />
            )}
          </section>
        )}

        {/* Compress result */}
        {compressed && !isProcessing && (
          <section className="result-card" aria-label="Compression result">
            <h2>{compressed.name}</h2>
            {savings > 0 ? (
              <p className="savings"><strong>{savings}% smaller</strong></p>
            ) : (
              <p className="savings savings-none">Already optimized — no further compression possible.</p>
            )}
            <div className="size-row">
              <span>{formatBytes(compressed.originalSize)}</span>
              <span aria-hidden="true">→</span>
              <span className="size-new">{formatBytes(compressed.compressedSize)}</span>
            </div>
            <div className="result-actions">
              <button type="button" className="btn btn-primary" onClick={handleDownloadCompressed}>
                Download compressed file
              </button>
              <button type="button" className="btn btn-ghost" onClick={clearResults}>Clear</button>
            </div>
          </section>
        )}

        {/* Merge queue */}
        {mode === 'merge' && mergeFiles.length > 0 && !merged && !isProcessing && (
          <section className="merge-queue" aria-label="Files to merge">
            <ul className="merge-list">
              {mergeFiles.map((f, i) => (
                <li key={`${f.name}-${i}`} className="merge-list-item">
                  <span className="merge-file-index">{i + 1}</span>
                  <span className="merge-file-name">{f.name}</span>
                  <span className="file-meta">{formatBytes(f.size)}</span>
                  <div className="merge-file-actions">
                    <button type="button" className="btn-icon" onClick={() => moveMergeFile(i, -1)}
                      disabled={i === 0} aria-label={`Move ${f.name} up`}>↑</button>
                    <button type="button" className="btn-icon" onClick={() => moveMergeFile(i, 1)}
                      disabled={i === mergeFiles.length - 1} aria-label={`Move ${f.name} down`}>↓</button>
                    <button type="button" className="btn-icon" onClick={() => removeMergeFile(i)}
                      aria-label={`Remove ${f.name}`}>✕</button>
                  </div>
                </li>
              ))}
            </ul>
            {mergeFiles.length < 2 && (
              <p className="merge-hint">Add at least one more PDF to merge.</p>
            )}
            <div className="result-actions">
              <button type="button" className="btn btn-primary" onClick={handleMerge}
                disabled={mergeFiles.length < 2}>
                Merge {mergeFiles.length} files
              </button>
              <button type="button" className="btn btn-ghost" onClick={clearResults}>Clear</button>
            </div>
          </section>
        )}

        {/* Merge result */}
        {merged && !isProcessing && (
          <section className="result-card" aria-label="Merge result">
            <h2>{merged.name}</h2>
            <p className="savings"><strong>{merged.fileCount} files combined</strong></p>
            <div className="result-actions">
              <button type="button" className="btn btn-primary"
                onClick={() => triggerDownload(merged.url, merged.name, false)}>
                Download merged PDF
              </button>
              <button type="button" className="btn btn-ghost" onClick={clearResults}>Clear</button>
            </div>
          </section>
        )}
      </main>

      <footer className="app-footer">
        <p>
          Powered by{' '}
          <a href="https://github.com/microsoft/markitdown" target="_blank" rel="noreferrer">markitdown</a>
          {' '}&amp; Ghostscript. Files are processed on your server and never stored.
        </p>
      </footer>
    </div>
  );
}

async function errorFromResponse(response, fallback) {
  let detail = fallback;
  try {
    const data = await response.json();
    detail = data.detail ?? fallback;
  } catch {
    /* response had no JSON body */
  }
  return new Error(detail);
}

function triggerDownload(url, filename, revoke) {
  const link = document.createElement('a');
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
  if (revoke) URL.revokeObjectURL(url);
}
