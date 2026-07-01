import React, { useState, useEffect, useMemo } from 'react';
import { File, Folder, Search, Loader2, Code2, Clipboard, ChevronRight, ChevronDown } from 'lucide-react';

const TreeNode = ({ node, level = 0, onFileSelect, selectedFile, expandedFolders, toggleFolder }) => {
  const isFolder = node.type === 'folder';
  
  if (node.name === 'root') {
    return (
      <div className="space-y-0.5">
        {Object.values(node.children)
          .sort((a, b) => {
            if (a.type === b.type) return a.name.localeCompare(b.name);
            return a.type === 'folder' ? -1 : 1;
          })
          .map(child => (
            <TreeNode 
              key={child.path} 
              node={child} 
              level={0} 
              onFileSelect={onFileSelect} 
              selectedFile={selectedFile} 
              expandedFolders={expandedFolders}
              toggleFolder={toggleFolder} 
            />
          ))}
      </div>
    );
  }

  const isSelected = selectedFile === node.path;
  const isExpanded = expandedFolders.has(node.path);

  return (
    <div className="w-full select-none">
      <div 
        className={`flex items-center gap-1.5 py-1.5 pr-2 rounded-lg cursor-pointer transition-colors ${isSelected ? 'bg-brand-500/10 text-brand-300 border border-brand-500/20' : 'hover:bg-dark-800/60 text-dark-300 border border-transparent'}`}
        style={{ paddingLeft: `${level * 14 + 8}px` }}
        onClick={() => isFolder ? toggleFolder(node.path) : onFileSelect(node.path)}
      >
        {isFolder ? (
          isExpanded ? <ChevronDown className="h-3.5 w-3.5 text-dark-500 flex-shrink-0" /> : <ChevronRight className="h-3.5 w-3.5 text-dark-500 flex-shrink-0" />
        ) : (
          <div className="w-3.5 flex-shrink-0" /> // spacer for files without chevron
        )}
        {isFolder ? (
          <Folder className="h-3.5 w-3.5 text-brand-400 flex-shrink-0" />
        ) : (
          <File className="h-3.5 w-3.5 text-indigo-400 flex-shrink-0" />
        )}
        <span className="text-[11px] font-mono truncate">{node.name}</span>
      </div>
      
      {isFolder && isExpanded && (
        <div className="flex flex-col mt-0.5">
          {Object.values(node.children)
            .sort((a, b) => {
              if (a.type === b.type) return a.name.localeCompare(b.name);
              return a.type === 'folder' ? -1 : 1;
            })
            .map(child => (
              <TreeNode 
                key={child.path} 
                node={child} 
                level={level + 1} 
                onFileSelect={onFileSelect} 
                selectedFile={selectedFile} 
                expandedFolders={expandedFolders}
                toggleFolder={toggleFolder} 
              />
          ))}
        </div>
      )}
    </div>
  );
};

export default function FileTree({ repo, structure, selectedFile, onFileSelect }) {
  const [search, setSearch] = useState('');
  const [fileContent, setFileContent] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [copySuccess, setCopySuccess] = useState(false);
  const [expandedFolders, setExpandedFolders] = useState(new Set());

  const files = structure?.tree || [];
  
  // Build nested folder tree structure
  const treeRoot = useMemo(() => {
    const root = { name: 'root', path: '', type: 'folder', children: {} };
    
    files.forEach((item) => {
      if (item.type !== 'blob') return; // Only process files, we will build folders dynamically
      
      // Filter by search
      if (search && !item.path.toLowerCase().includes(search.toLowerCase())) return;

      const parts = item.path.split('/');
      let current = root;
      let currentPath = '';

      parts.forEach((part, index) => {
        currentPath = currentPath ? `${currentPath}/${part}` : part;
        const isFile = index === parts.length - 1;

        if (!current.children[part]) {
          current.children[part] = {
            name: part,
            path: currentPath,
            type: isFile ? 'file' : 'folder',
            children: {}
          };
        }
        current = current.children[part];
      });
    });
    
    return root;
  }, [files, search]);

  // Load content when a file is selected
  useEffect(() => {
    if (!selectedFile) return;
    
    // Auto-expand folders leading to the selected file
    const parts = selectedFile.split('/');
    if (parts.length > 1) {
      const newExpanded = new Set(expandedFolders);
      let currentPath = '';
      for (let i = 0; i < parts.length - 1; i++) {
        currentPath = currentPath ? `${currentPath}/${parts[i]}` : parts[i];
        newExpanded.add(currentPath);
      }
      setExpandedFolders(newExpanded);
    }

    setIsLoading(true);
    setFileContent('');
    
    fetch(`http://localhost:8000/api/repositories/${repo.id}/files?path=${encodeURIComponent(selectedFile)}`)
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
  }, [selectedFile, repo.id]);

  const toggleFolder = (path) => {
    const newSet = new Set(expandedFolders);
    if (newSet.has(path)) {
      newSet.delete(path);
    } else {
      newSet.add(path);
    }
    setExpandedFolders(newSet);
  };

  const handleCopyCode = () => {
    navigator.clipboard.writeText(fileContent);
    setCopySuccess(true);
    setTimeout(() => setCopySuccess(false), 2000);
  };

  return (
    <div className="flex h-[72vh] min-h-[560px] border border-dark-800 bg-dark-950/20 rounded-2xl overflow-hidden">
      
      {/* Sidebar: Search & Folder Tree */}
      <div className="w-1/3 border-r border-dark-800 bg-dark-950/40 p-4 flex flex-col h-full">
        <div className="relative mb-4 flex-shrink-0">
          <Search className="absolute left-3 top-3 h-4 w-4 text-dark-500" />
          <input
            type="text"
            placeholder="Search files..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="w-full bg-dark-900 border border-dark-800 rounded-lg pl-9 pr-3 py-2 text-xs text-white placeholder-dark-500 focus:outline-none focus:border-brand-500/50"
          />
        </div>

        <div className="flex-1 overflow-y-auto pr-2 custom-scrollbar">
          {Object.keys(treeRoot.children).length === 0 ? (
            <div className="text-center text-xs text-dark-500 py-10">No code files matched.</div>
          ) : (
            <TreeNode 
              node={treeRoot} 
              onFileSelect={onFileSelect} 
              selectedFile={selectedFile}
              expandedFolders={expandedFolders}
              toggleFolder={toggleFolder}
            />
          )}
        </div>
      </div>

      {/* Editor Panel: File Viewer */}
      <div className="flex-1 flex flex-col bg-dark-900/10 h-full">
        {selectedFile ? (
          <div className="flex-1 flex flex-col h-full overflow-hidden">
            {/* Header bar */}
            <div className="bg-dark-950/80 border-b border-dark-800/80 px-5 py-3 flex justify-between items-center">
              <div className="flex items-center gap-2">
                <Code2 className="h-4 w-4 text-brand-400" />
                <span className="text-xs font-mono font-bold text-white truncate max-w-md" title={selectedFile}>
                  {selectedFile}
                </span>
              </div>
              {fileContent && !isLoading && (
                <button
                  onClick={handleCopyCode}
                  className="text-[10px] font-semibold text-dark-300 hover:text-white flex items-center gap-1 bg-dark-900 border border-dark-800 px-2 py-1 rounded transition-colors hover:bg-dark-800"
                >
                  <Clipboard className="h-3 w-3" />
                  <span>{copySuccess ? 'Copied!' : 'Copy Code'}</span>
                </button>
              )}
            </div>

            {/* Content view */}
            <div className="flex-1 overflow-y-auto p-5 font-mono text-[11px] text-dark-200 bg-dark-950/40 relative custom-scrollbar">
              {isLoading ? (
                <div className="absolute inset-0 flex flex-col items-center justify-center bg-dark-950/30">
                  <Loader2 className="h-6 w-6 text-brand-400 animate-spin mb-3" />
                  <span className="text-xs text-dark-400">Loading file contents...</span>
                </div>
              ) : (
                <pre className="whitespace-pre overflow-x-auto leading-relaxed h-full">
                  <code>{fileContent}</code>
                </pre>
              )}
            </div>
          </div>
        ) : (
          <div className="flex-1 flex flex-col items-center justify-center text-center p-10 h-full">
            <Code2 className="h-10 w-10 text-dark-600 mb-3 animate-pulse" />
            <h4 className="text-white font-bold text-sm mb-1">Code Viewer</h4>
            <p className="text-dark-500 text-xs max-w-xs">Select any file from the explorer or click a node in the Architecture Map to view its contents.</p>
          </div>
        )}
      </div>

    </div>
  );
}
