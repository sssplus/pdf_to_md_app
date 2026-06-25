import React, { useState, useCallback } from 'react';
import './App.css';
import { useDropzone } from 'react-dropzone';
import { marked } from 'marked';
import DOMPurify from 'dompurify';

function App() {
  const [markdownContent, setMarkdownContent] = useState('');
  const [fileName, setFileName] = useState('');
  const [isConverting, setIsConverting] = useState(false);
  const [error, setError] = useState('');

  const onDrop = useCallback(async (acceptedFiles) => {
    setError(''); // Clear previous errors
    if (acceptedFiles.length === 0) {
      setError('Please upload a .pdf or .doc(x) file.');
      return;
    }

    const file = acceptedFiles[0];
    const fileExtension = file.name.split('.').pop().toLowerCase();

    if (fileExtension !== 'pdf' && fileExtension !== 'docx' && fileExtension !== 'doc') {
      setError('Unsupported file type. Only PDF and DOC(X) are allowed.');
      return;
    }

    setFileName(file.name);
    setIsConverting(true);
    setMarkdownContent(''); // Clear previous content

    const formData = new FormData();
    formData.append('file', file);

    try {
      const response = await fetch('http://localhost:8000/api/convert', {
        method: 'POST',
        body: formData,
      });

      if (!response.ok) {
        const errorData = await response.json();
        throw new Error(errorData.detail || 'Failed to convert document.');
      }

      const mdText = await response.text();
      setMarkdownContent(mdText);
    } catch (err) {
      console.error('Conversion error:', err);
      setError(`Conversion failed: ${err.message}`);
    } finally {
      setIsConverting(false);
    }
  }, []);

  const { getRootProps, getInputProps, isDragActive } = useDropzone({ onDrop, multiple: false });

  const getCleanedMarkdownHtml = () => {
    if (!markdownContent) return { __html: '' };
    const rawMarkup = marked.parse(markdownContent);
    const cleanMarkup = DOMPurify.sanitize(rawMarkup);
    return { __html: cleanMarkup };
  };

  const Path = (fullPath) => {
    const parts = fullPath.split('.');
    return {
      name: fullPath,
      with_suffix: (newSuffix) => {
        if (parts.length > 1) {
          parts.pop(); // Remove old suffix
        }
        return `${parts.join('.')}${newSuffix}`;
      },
    };
  };

  const downloadMarkdown = () => {
    if (markdownContent) {
      const blob = new Blob([markdownContent], { type: 'text/markdown' });
      const url = URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url;
      link.download = Path(fileName).with_suffix(".md");
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);
      URL.revokeObjectURL(url);
    }
  };

  return (
    <div className="App dark-mode">
      <h1>Doc2MD Converter</h1>
      
      <div {...getRootProps()} className={`dropzone ${isDragActive ? 'active' : ''}`}>
        <input {...getInputProps()} />
        {isDragActive ? (
          <p>Drop the file here ...</p>
        ) : (
          <p>Drag 'n' drop a PDF or DOCX file here, or click to select a file</p>
        )}
      </div>

      {isConverting && <div className="loader"></div>}

      {error && <div className="error-message">{error}</div>}

      {markdownContent && (
        <div className="preview-container">
          <div className="preview-header">
            <h2>Preview: {Path(fileName).with_suffix(".md")}</h2>
            <button className="download-btn" onClick={downloadMarkdown}>
              Download .md
            </button>
          </div>
          <div 
            className="markdown-body"
            dangerouslySetInnerHTML={getCleanedMarkdownHtml()} 
          />
        </div>
      )}
    </div>
  );
}

export default App;
