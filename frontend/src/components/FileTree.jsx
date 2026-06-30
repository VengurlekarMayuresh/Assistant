import React, { useState, useEffect } from 'react';
import { File, Folder, Search, Loader2, Code2, Clipboard } from 'lucide-react';

export default function FileTree({ repo, structure }) {
  const [search, setSearch] = useState('');
  const [selectedFile, setSelectedFile] = useState(null);
  const [fileContent, setFileContent] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [copySuccess, setCopySuccess] = useState(false);

  const files = structure?.tree || [];
  
  // Filter search matches
  const filteredFiles = files.filter(item => 
    item.type === 'blob' && 
    item.path.toLowerCase().includes(search.toLowerCase())
  ).slice(0, 100); // limit to 100 entries for UX responsiveness

  const handleFileClick = (path) => {
    setSelectedFile(path);
    setIsLoading(true);
    setFileContent('');
    
    // Fetch file content from backend
    fetch(`http://localhost:8000/api/repositories/${repo.id}/files?path=${encodeURIComponent(path)}`)
      .then(res => {
        if (!res.ok) throw new Error("Failed to load file content.");
        return res.json();
      })
      .then(data => {
        setFileContent(data.content || '');
        setIsLoading(false);
      })
      .catch(err => {
        setFileContent(`Error loading file: ${err.message}`);
        setIsLoading(false);
      });
  };

  const handleCopyCode = () => {
    navigator.clipboard.writeText(fileContent);
    setCopySuccess(true);
    setTimeout(() => setCopySuccess(false), 2000);
  };

  return (
    <div className="flex h-full border border-dark-800 bg-dark-950/20 rounded-2xl overflow-hidden min-h-[500px]">
      
      {/* Sidebar: Search & File List */}
      <div className="w-1/3 border-r border-dark-800 bg-dark-950/40 p-4 flex flex-col">
        <div className="relative mb-3">
          <Search className="absolute left-3 top-3 h-4 w-4 text-dark-500" />
          <input
            type="text"
            placeholder="Search files..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="w-full bg-dark-900 border border-dark-800 rounded-lg pl-9 pr-3 py-2 text-xs text-white placeholder-dark-500 focus:outline-none focus:border-brand-500/50"
          />
        </div>

        <div className="flex-1 overflow-y-auto space-y-1 pr-1">
          {filteredFiles.length === 0 ? (
            <div className="text-center text-xs text-dark-500 py-10">No code files matched.</div>
          ) : (
            filteredFiles.map((file) => (
              <button
                key={file.path}
                onClick={() => handleFileClick(file.path)}
                className={`w-full flex items-center gap-2 px-2.5 py-2 rounded-lg text-left text-xs font-mono transition-all ${
                  selectedFile === file.path
                    ? 'bg-brand-500/10 text-brand-300 border border-brand-500/20'
                    : 'text-dark-300 hover:bg-dark-900/60 border border-transparent'
                }`}
              >
                <File className="h-3.5 w-3.5 flex-shrink-0" />
                <span className="truncate">{file.path}</span>
              </button>
            ))
          )}
        </div>
      </div>

      {/* Editor Panel: File Viewer */}
      <div className="flex-1 flex flex-col bg-dark-900/10">
        {selectedFile ? (
          <div className="flex-1 flex flex-col h-full overflow-hidden">
            {/* Header bar */}
            <div className="bg-dark-950/80 border-b border-dark-800/80 px-5 py-3 flex justify-between items-center">
              <div className="flex items-center gap-2">
                <Code2 className="h-4 w-4 text-brand-400" />
                <span className="text-xs font-mono font-bold text-white">{selectedFile}</span>
              </div>
              {fileContent && !isLoading && (
                <button
                  onClick={handleCopyCode}
                  className="text-[10px] font-semibold text-dark-300 hover:text-white flex items-center gap-1 bg-dark-900 border border-dark-800 px-2 py-1 rounded"
                >
                  <Clipboard className="h-3 w-3" />
                  <span>{copySuccess ? 'Copied!' : 'Copy Code'}</span>
                </button>
              )}
            </div>

            {/* Content view */}
            <div className="flex-1 overflow-y-auto p-5 font-mono text-[11px] text-dark-200 bg-dark-950/40 relative">
              {isLoading ? (
                <div className="absolute inset-0 flex items-center justify-center bg-dark-950/30">
                  <Loader2 className="h-6 w-6 text-brand-400 animate-spin" />
                </div>
              ) : (
                <pre className="whitespace-pre overflow-x-auto leading-relaxed">
                  <code>{fileContent}</code>
                </pre>
              )}
            </div>
          </div>
        ) : (
          <div className="flex-1 flex flex-col items-center justify-center text-center p-10">
            <Code2 className="h-10 w-10 text-dark-600 mb-3 animate-pulse" />
            <h4 className="text-white font-bold text-sm mb-1">Code Viewer</h4>
            <p className="text-dark-500 text-xs max-w-xs">Select any file from the list to explore its contents here.</p>
          </div>
        )}
      </div>

    </div>
  );
}
