import React, { useState, useEffect } from 'react';
import axios from 'axios';
import { GitCommit, GitPullRequest, Loader2, Calendar, User } from 'lucide-react';

export default function GitHistory({ repoId }) {
  const [activeTab, setActiveTab] = useState('commits');
  const [data, setData] = useState({ commits: [], prs: [] });
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    if (!repoId) return;
    
    const fetchData = async () => {
      setLoading(true);
      setError(null);
      try {
        const [commitsRes, prsRes] = await Promise.all([
          axios.get(`http://localhost:8000/api/repositories/${repoId}/commits`),
          axios.get(`http://localhost:8000/api/repositories/${repoId}/prs`)
        ]);
        
        setData({
          commits: commitsRes.data,
          prs: prsRes.data
        });
      } catch (err) {
        console.error('Failed to fetch git history:', err);
        setError('Unable to load git history. Please ensure the repository is fully scanned.');
      } finally {
        setLoading(false);
      }
    };
    
    fetchData();
  }, [repoId]);

  if (loading) {
    return (
      <div className="w-full h-[72vh] min-h-[560px] bg-dark-950/20 rounded-2xl border border-dark-800/80 flex flex-col items-center justify-center text-center">
        <Loader2 className="h-8 w-8 text-brand-500 animate-spin mb-4" />
        <div className="text-sm font-semibold text-white">Fetching Git History...</div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="w-full h-[72vh] min-h-[560px] bg-dark-950/20 rounded-2xl border border-dark-800/80 flex items-center justify-center text-center px-6">
        <div className="text-sm font-semibold text-red-400">{error}</div>
      </div>
    );
  }

  return (
    <div className="w-full h-[72vh] min-h-[560px] bg-dark-950/20 rounded-2xl border border-dark-800/80 flex flex-col overflow-hidden">
      {/* Tabs */}
      <div className="flex border-b border-dark-800 bg-dark-900/50">
        <button
          onClick={() => setActiveTab('commits')}
          className={`flex-1 py-3 text-sm font-bold flex items-center justify-center gap-2 transition-colors ${
            activeTab === 'commits' ? 'text-brand-400 border-b-2 border-brand-500 bg-brand-500/5' : 'text-dark-400 hover:text-dark-200'
          }`}
        >
          <GitCommit className="h-4 w-4" />
          Recent Commits
        </button>
        <button
          onClick={() => setActiveTab('prs')}
          className={`flex-1 py-3 text-sm font-bold flex items-center justify-center gap-2 transition-colors ${
            activeTab === 'prs' ? 'text-brand-400 border-b-2 border-brand-500 bg-brand-500/5' : 'text-dark-400 hover:text-dark-200'
          }`}
        >
          <GitPullRequest className="h-4 w-4" />
          Pull Requests
        </button>
      </div>

      {/* Content */}
      <div className="flex-1 overflow-y-auto p-4 space-y-3">
        {activeTab === 'commits' && (
          data.commits.length === 0 ? (
            <div className="text-center text-dark-400 mt-10">No commits found.</div>
          ) : (
            data.commits.map((commit, idx) => (
              <div key={commit.sha || idx} className="bg-dark-900/50 border border-dark-800 rounded-xl p-4 flex gap-4">
                <div className="mt-1">
                  <div className="h-8 w-8 rounded-full bg-brand-500/20 flex items-center justify-center border border-brand-500/30">
                    <GitCommit className="h-4 w-4 text-brand-400" />
                  </div>
                </div>
                <div className="flex-1">
                  <div className="text-sm font-bold text-white mb-1">
                    {commit.commit?.message?.split('\\n')[0]}
                  </div>
                  <div className="flex items-center gap-4 text-xs text-dark-400">
                    <span className="flex items-center gap-1">
                      <User className="h-3 w-3" />
                      {commit.commit?.author?.name || 'Unknown'}
                    </span>
                    <span className="flex items-center gap-1">
                      <Calendar className="h-3 w-3" />
                      {new Date(commit.commit?.author?.date).toLocaleDateString()}
                    </span>
                    <span className="font-mono bg-dark-950 px-2 rounded border border-dark-800 text-dark-300">
                      {commit.sha?.substring(0, 7)}
                    </span>
                  </div>
                </div>
              </div>
            ))
          )
        )}

        {activeTab === 'prs' && (
          data.prs.length === 0 ? (
            <div className="text-center text-dark-400 mt-10">No pull requests found.</div>
          ) : (
            data.prs.map((pr, idx) => (
              <div key={pr.id || idx} className="bg-dark-900/50 border border-dark-800 rounded-xl p-4 flex gap-4">
                <div className="mt-1">
                  <div className="h-8 w-8 rounded-full bg-green-500/20 flex items-center justify-center border border-green-500/30">
                    <GitPullRequest className="h-4 w-4 text-green-400" />
                  </div>
                </div>
                <div className="flex-1">
                  <div className="flex justify-between items-start">
                    <div className="text-sm font-bold text-white mb-1 hover:text-brand-300 cursor-pointer" onClick={() => window.open(pr.html_url, '_blank')}>
                      {pr.title}
                    </div>
                    <span className={`text-[10px] font-bold px-2 py-0.5 rounded-full uppercase tracking-wider ${
                      pr.state === 'open' ? 'bg-green-500/20 text-green-400 border border-green-500/30' : 'bg-purple-500/20 text-purple-400 border border-purple-500/30'
                    }`}>
                      {pr.state}
                    </span>
                  </div>
                  <div className="flex items-center gap-4 text-xs text-dark-400 mt-1">
                    <span className="flex items-center gap-1">
                      <User className="h-3 w-3" />
                      {pr.user?.login || 'Unknown'}
                    </span>
                    <span>#{pr.number}</span>
                    <span className="flex items-center gap-1">
                      <Calendar className="h-3 w-3" />
                      {new Date(pr.created_at).toLocaleDateString()}
                    </span>
                  </div>
                </div>
              </div>
            ))
          )
        )}
      </div>
    </div>
  );
}
