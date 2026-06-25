import { useCallback, useMemo, useState } from 'react';
import { useDropzone } from 'react-dropzone';
import { marked } from 'marked';
import DOMPurify from 'dompurify';
import './App.css';

// Base URL of the backend API. Configurable at build time via VITE_API_URL.
const API_URL = (import.meta.env.VITE_API_URL ?? 'http://localhost:8000').replace(/\/$/, '');

const ACCEPTED_EXTENSIONS = ['pdf', 'docx', 'doc'];
const ACCEPT = {
  'application/pdf': ['.pdf'],
  'application/msword': ['.doc'],
  'application/vnd.openxmlformats-officedocument.wordprocessingml.document': ['.docx'],
};

// Replace the file's extension with ".md" (e.g. "report.pdf" -> "report.md").
function toMarkdownFilename(name) {
  if (!name) return 'document.md';
  const dot = name.lastIndexOf('.');
  const base = dot > 0 ? name.slice(0, dot) : name;
  return `${base}.md`;
}

function formatBytes(bytes) {
  if (!bytes) return '';
  const units = ['B', 'KB', 'MB', 'GB'];
  const i = Math.floor(Math.log(bytes) / Math.log(1024));
  return `${(bytes / 1024 ** i).toFixed(i === 0 ? 0 : 1)} ${units[i]}`;
}

export default function App() {
  const [markdown, setMarkdown] = useState('');
  const [file, setFile] = useState(null);
  const [isConverting, setIsConverting] = useState(false);
  const [error, setError] = useState('');
  const [showRaw, setShowRaw] = useState(false);
  const [copied, setCopied] = useState(false);

  const reset = useCallback(() => {
    setMarkdown('');
    setFile(null);
    setError('');
    setShowRaw(false);
    setCopied(false);
  }, []);

  const onDrop = useCallback(async (acceptedFiles, fileRejections) => {
    setError('');
    setCopied(false);

    if (fileRejections.length > 0) {
      setError('Unsupported file type. Please upload a PDF, DOC, or DOCX file.');
      return;
    }
    if (acceptedFiles.length === 0) return;

    const selected = acceptedFiles[0];
    const extension = selected.name.split('.').pop().toLowerCase();
    if (!ACCEPTED_EXTENSIONS.includes(extension)) {
      setError('Unsupported file type. Please upload a PDF, DOC, or DOCX file.');
      return;
    }

    setFile(selected);
    setIsConverting(true);
    setMarkdown('');

    const formData = new FormData();
    formData.append('file', selected);

    try {
      const response = await fetch(`${API_URL}/api/convert`, {
        method: 'POST',
        body: formData,
      });

      if (!response.ok) {
        let detail = 'Failed to convert the document.';
        try {
          const data = await response.json();
          detail = data.detail ?? detail;
        } catch {
          /* response had no JSON body */
        }
        throw new Error(detail);
      }

      setMarkdown(await response.text());
    } catch (err) {
      const message = err instanceof TypeError
        ? 'Could not reach the conversion server. Is the backend running?'
        : err.message;
      setError(message);
    } finally {
      setIsConverting(false);
    }
  }, []);

  const { getRootProps, getInputProps, isDragActive } = useDropzone({
    onDrop,
    accept: ACCEPT,
    multiple: false,
    disabled: isConverting,
  });

  const renderedHtml = useMemo(() => {
    if (!markdown) return '';
    return DOMPurify.sanitize(marked.parse(markdown));
  }, [markdown]);

  const outputName = toMarkdownFilename(file?.name);

  const handleCopy = useCallback(async () => {
    try {
      await navigator.clipboard.writeText(markdown);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      setError('Could not copy to clipboard.');
    }
  }, [markdown]);

  const handleDownload = useCallback(() => {
    const blob = new Blob([markdown], { type: 'text/markdown;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = outputName;
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    URL.revokeObjectURL(url);
  }, [markdown, outputName]);

  return (
    <div className="app">
      <header className="app-header">
        <h1>Doc2MD</h1>
        <p className="tagline">Convert PDF, DOC, and DOCX files to clean Markdown.</p>
      </header>

      <main className="app-main">
        <div
          {...getRootProps()}
          className={`dropzone ${isDragActive ? 'active' : ''} ${isConverting ? 'disabled' : ''}`}
          aria-label="File upload area"
        >
          <input {...getInputProps()} />
          <svg className="dropzone-icon" viewBox="0 0 24 24" aria-hidden="true">
            <path d="M12 16V4m0 0l-4 4m4-4l4 4M4 16v2a2 2 0 002 2h12a2 2 0 002-2v-2" />
          </svg>
          {isDragActive ? (
            <p>Drop the file to convert it…</p>
          ) : (
            <p>
              <strong>Drag &amp; drop</strong> a PDF or Word document here,
              <br />
              or click to browse
            </p>
          )}
          <span className="dropzone-hint">Supported: .pdf, .doc, .docx</span>
        </div>

        {isConverting && (
          <div className="status" role="status">
            <div className="loader" aria-hidden="true" />
            <span>Converting {file?.name}…</span>
          </div>
        )}

        {error && (
          <div className="error-message" role="alert">
            {error}
          </div>
        )}

        {markdown && !isConverting && (
          <section className="preview-container" aria-label="Conversion result">
            <div className="preview-header">
              <div className="preview-title">
                <h2>{outputName}</h2>
                {file && <span className="file-meta">{formatBytes(file.size)}</span>}
              </div>
              <div className="preview-actions">
                <div className="toggle" role="tablist" aria-label="View mode">
                  <button
                    type="button"
                    role="tab"
                    aria-selected={!showRaw}
                    className={!showRaw ? 'active' : ''}
                    onClick={() => setShowRaw(false)}
                  >
                    Preview
                  </button>
                  <button
                    type="button"
                    role="tab"
                    aria-selected={showRaw}
                    className={showRaw ? 'active' : ''}
                    onClick={() => setShowRaw(true)}
                  >
                    Raw
                  </button>
                </div>
                <button type="button" className="btn" onClick={handleCopy}>
                  {copied ? 'Copied!' : 'Copy'}
                </button>
                <button type="button" className="btn btn-primary" onClick={handleDownload}>
                  Download
                </button>
                <button type="button" className="btn btn-ghost" onClick={reset}>
                  Clear
                </button>
              </div>
            </div>

            {showRaw ? (
              <pre className="markdown-raw">{markdown}</pre>
            ) : (
              <div
                className="markdown-body"
                // Rendered by marked, then sanitized by DOMPurify above.
                dangerouslySetInnerHTML={{ __html: renderedHtml }}
              />
            )}
          </section>
        )}
      </main>

      <footer className="app-footer">
        <p>
          Powered by{' '}
          <a href="https://github.com/microsoft/markitdown" target="_blank" rel="noreferrer">
            markitdown
          </a>
          . Files are processed on your server and never stored.
        </p>
      </footer>
    </div>
  );
}
