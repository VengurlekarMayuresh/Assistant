import React, { useState, useEffect } from 'react';
import Navbar from './components/Navbar';
import RepoGrid from './components/RepoGrid';
import ChatPanel from './components/ChatPanel';
import ArchitectureMap from './components/ArchitectureMap';
import FileTree from './components/FileTree';
import GitHistory from './components/GitHistory';
import { GitBranch, Star, Code, BarChart2, MessageSquare, Compass, ShieldAlert, Cpu, History } from 'lucide-react';
import axios from 'axios';

export default function App() {
  const [repos, setRepos] = useState([]);
  const [activeRepo, setActiveRepo] = useState(null);
  const [activeSession, setActiveSession] = useState(null);
  const [messages, setMessages] = useState([]);
  const [isLoadingRepos, setIsLoadingRepos] = useState(false);
  const [activeTab, setActiveTab] = useState('architecture'); // 'architecture' | 'files' | 'overview' | 'history'
  const [selectedFile, setSelectedFile] = useState(null);

  // Fetch all repositories from backend
  const fetchRepos = async () => {
    try {
      const response = await axios.get('http://localhost:8000/api/repositories');
      setRepos(response.data);
    } catch (err) {
      console.error('Error fetching repositories:', err);
    }
  };

  useEffect(() => {
    fetchRepos();
  }, []);

  const handleSelectRepo = async (repo) => {
    try {
      const res = await axios.post('http://localhost:8000/api/sessions', {
        repository_id: repo.id
      });
      const session = res.data;
      
      setActiveRepo(repo);
      setActiveSession(session);
      setMessages([]);
      setActiveTab('architecture'); // Default to architecture map
      setSelectedFile(null);
    } catch (err) {
      console.error('Error starting session:', err);
      alert('Failed to start chat session with this repository. Check if backend is active.');
    }
  };

  const handleBackToDashboard = () => {
    setActiveRepo(null);
    setActiveSession(null);
    setMessages([]);
    setSelectedFile(null);
    fetchRepos();
  };

  const handleNodeClick = (filePath) => {
    // When a node is clicked in ArchitectureMap, open the file explorer and select it
    setSelectedFile(filePath);
    setActiveTab('files');
  };

  const handleAddRepo = async (url) => {
    setIsLoadingRepos(true);
    try {
      await axios.post('http://localhost:8000/api/repositories', { url });
      await fetchRepos();
    } catch (err) {
      console.error('Error registering repository:', err);
      alert(err.response?.data?.detail || 'Failed to scan repository. Please verify the URL and your GitHub token.');
    } finally {
      setIsLoadingRepos(false);
    }
  };

  return (
    <div className="flex flex-col min-h-screen bg-dark-950 text-dark-100 font-sans">
      <Navbar activeRepo={activeRepo} onBack={handleBackToDashboard} />

      <main className="flex-1 flex flex-col min-h-0">
        {!activeRepo ? (
          // Home Dashboard view
          <RepoGrid
            repos={repos}
            onSelectRepo={handleSelectRepo}
            onAddRepo={handleAddRepo}
            isLoading={isLoadingRepos}
          />
        ) : (
          // Exploration Workspace view (split view)
          <div className="flex-1 flex flex-col md:flex-row min-h-0 h-[calc(100vh-4rem)]">
            
            {/* Left Column: Chat & Agent Logs Checklist (40% width) */}
            <div className="w-full md:w-[38%] border-r border-dark-800 flex flex-col h-full bg-dark-950/40">
              <div className="px-6 py-4 border-b border-dark-800 bg-dark-900/40 flex items-center gap-2">
                <MessageSquare className="h-4 w-4 text-brand-400" />
                <span className="text-xs font-bold text-white tracking-wider">AGENT CHAT WORKSPACE</span>
              </div>
              <div className="flex-1 min-h-0">
                <ChatPanel
                  sessionId={activeSession.id}
                  messages={messages}
                  setMessages={setMessages}
                  activeRepo={activeRepo}
                />
              </div>
            </div>

            {/* Right Column: Codebase Navigation & React Flow (62% width) */}
            <div className="flex-1 flex flex-col h-full min-h-0 bg-dark-950/20">
              {/* Tab Navigation header */}
              <div className="border-b border-dark-800 bg-dark-900/40 px-6 py-2 flex items-center justify-between">
                <div className="flex gap-2 flex-wrap">
                  <button
                    onClick={() => setActiveTab('architecture')}
                    className={`flex items-center gap-2 px-3 py-2 rounded-lg text-xs font-semibold border transition-all ${
                      activeTab === 'architecture'
                        ? 'bg-brand-500/10 text-brand-300 border-brand-500/20'
                        : 'text-dark-400 hover:text-dark-100 border-transparent'
                    }`}
                  >
                    <Compass className="h-3.5 w-3.5" />
                    <span>Architecture Map</span>
                  </button>

                  <button
                    onClick={() => setActiveTab('files')}
                    className={`flex items-center gap-2 px-3 py-2 rounded-lg text-xs font-semibold border transition-all ${
                      activeTab === 'files'
                        ? 'bg-brand-500/10 text-brand-300 border-brand-500/20'
                        : 'text-dark-400 hover:text-dark-100 border-transparent'
                    }`}
                  >
                    <Code className="h-3.5 w-3.5" />
                    <span>File Explorer</span>
                  </button>

                  <button
                    onClick={() => setActiveTab('overview')}
                    className={`flex items-center gap-2 px-3 py-2 rounded-lg text-xs font-semibold border transition-all ${
                      activeTab === 'overview'
                        ? 'bg-brand-500/10 text-brand-300 border-brand-500/20'
                        : 'text-dark-400 hover:text-dark-100 border-transparent'
                    }`}
                  >
                    <BarChart2 className="h-3.5 w-3.5" />
                    <span>Repository Overview</span>
                  </button>

                  <button
                    onClick={() => setActiveTab('history')}
                    className={`flex items-center gap-2 px-3 py-2 rounded-lg text-xs font-semibold border transition-all ${
                      activeTab === 'history'
                        ? 'bg-brand-500/10 text-brand-300 border-brand-500/20'
                        : 'text-dark-400 hover:text-dark-100 border-transparent'
                    }`}
                  >
                    <History className="h-3.5 w-3.5" />
                    <span>Git History</span>
                  </button>
                </div>

                <div className="text-[10px] font-mono text-dark-500 hidden sm:block">
                  Workspace Session: {activeSession.id.slice(0, 8)}...
                </div>
              </div>

              {/* Tab Content Panel */}
              <div className="flex-1 p-6 min-h-[560px] md:min-h-0 overflow-hidden">
                {activeTab === 'architecture' && (
                  <ArchitectureMap repoId={activeRepo.id} onNodeClick={handleNodeClick} />
                )}

                {activeTab === 'files' && (
                  <FileTree repo={activeRepo} structure={activeRepo.structure_json} selectedFile={selectedFile} onFileSelect={setSelectedFile} />
                )}

                {activeTab === 'history' && (
                  <GitHistory repoId={activeRepo.id} />
                )}

                {activeTab === 'overview' && (
                  <div className="h-full overflow-y-auto space-y-6 max-w-4xl pr-2">
                    
                    {/* Repo Card */}
                    <div className="glass-panel rounded-2xl p-6 border border-dark-800">
                      <div className="flex items-center gap-2 text-brand-400 text-xs font-bold tracking-wider mb-2">
                        <Cpu className="h-4 w-4" />
                        <span>METADATA AND DIAGNOSTICS</span>
                      </div>
                      <h2 className="text-2xl font-bold text-white mb-2 font-sans">
                        {activeRepo.owner} / {activeRepo.name}
                      </h2>
                      <p className="text-sm text-dark-300 mb-6 leading-relaxed">
                        This repository was parsed dynamically. The system extracted files, import hierarchies, config setups, and languages to generate its agentic memory cache.
                      </p>
                      
                      <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
                        <div className="bg-dark-950/40 border border-dark-850 p-4 rounded-xl text-center">
                          <div className="text-[10px] text-dark-400 font-semibold mb-1">TOTAL FILES DETECTED</div>
                          <div className="text-xl font-bold text-white font-mono">
                            {activeRepo.structure_json?.tree?.length || 0}
                          </div>
                        </div>
                        
                        <div className="bg-dark-950/40 border border-dark-850 p-4 rounded-xl text-center">
                          <div className="text-[10px] text-dark-400 font-semibold mb-1">FRAMEWORKS FOUND</div>
                          <div className="text-xl font-bold text-white font-mono">
                            {activeRepo.frameworks?.length || 0}
                          </div>
                        </div>

                        <div className="bg-dark-950/40 border border-dark-850 p-4 rounded-xl text-center col-span-2">
                          <div className="text-[10px] text-dark-400 font-semibold mb-1">GITHUB URL</div>
                          <div className="text-xs text-brand-300 font-mono truncate pt-1">
                            <a href={activeRepo.url} target="_blank" rel="noreferrer" className="hover:underline">
                              {activeRepo.url}
                            </a>
                          </div>
                        </div>
                      </div>
                    </div>

                    {/* Detected Frameworks details */}
                    {activeRepo.frameworks && activeRepo.frameworks.length > 0 && (
                      <div className="glass-panel rounded-2xl p-6 border border-dark-800">
                        <h3 className="text-sm font-bold text-white tracking-wider mb-4 uppercase">Detected Technologies</h3>
                        <div className="flex flex-wrap gap-2">
                          {activeRepo.frameworks.map((f, i) => (
                            <span key={i} className="px-3 py-1.5 rounded-lg bg-indigo-500/10 text-indigo-300 border border-indigo-500/20 text-xs font-semibold">
                              {f}
                            </span>
                          ))}
                        </div>
                      </div>
                    )}

                    {/* Language Breakdown */}
                    {activeRepo.languages && Object.keys(activeRepo.languages).length > 0 && (
                      <div className="glass-panel rounded-2xl p-6 border border-dark-800">
                        <h3 className="text-sm font-bold text-white tracking-wider mb-4 uppercase">Codebase Languages</h3>
                        <div className="space-y-3">
                          {Object.entries(activeRepo.languages).map(([lang, bytes]) => {
                            const totalBytes = Object.values(activeRepo.languages).reduce((a, b) => a + b, 0);
                            const percent = (bytes / totalBytes) * 100;
                            return (
                              <div key={lang} className="space-y-1.5">
                                <div className="flex justify-between text-xs font-semibold">
                                  <span className="text-white">{lang}</span>
                                  <span className="text-dark-400">{percent.toFixed(1)}% ({Math.round(bytes / 1024)} KB)</span>
                                </div>
                                <div className="h-2 w-full bg-dark-950 rounded-full overflow-hidden border border-dark-850">
                                  <div
                                    className="h-full bg-brand-500 rounded-full bg-gradient-to-r from-brand-600 to-indigo-500"
                                    style={{ width: `${percent}%` }}
                                  />
                                </div>
                              </div>
                            );
                          })}
                        </div>
                      </div>
                    )}

                  </div>
                )}
              </div>
            </div>

          </div>
        )}
      </main>
    </div>
  );
}
