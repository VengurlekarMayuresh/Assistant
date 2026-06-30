import React, { useState } from 'react';
import { GitPullRequest, Search, Star, Layers, ArrowRight, Loader2 } from 'lucide-react';

export default function RepoGrid({ repos, onSelectRepo, onAddRepo, isLoading }) {
  const [url, setUrl] = useState('');
  const [error, setError] = useState('');

  const handleSubmit = (e) => {
    e.preventDefault();
    if (!url.trim()) return;
    if (!url.includes('github.com')) {
      setError('Please enter a valid github.com repository URL.');
      return;
    }
    setError('');
    onAddRepo(url);
    setUrl('');
  };

  const getLanguageColor = (lang) => {
    const colors = {
      Python: '#3572A5',
      JavaScript: '#f1e05a',
      TypeScript: '#3178c6',
      HTML: '#e34c26',
      CSS: '#563d7c',
      Shell: '#89e051',
      Go: '#00ADD8',
      Rust: '#dea584'
    };
    return colors[lang] || '#8b949e';
  };

  return (
    <div className="mx-auto max-w-7xl px-6 py-10">
      {/* Hero Section */}
      <div className="text-center max-w-3xl mx-auto mb-16">
        <h1 className="text-4xl font-extrabold tracking-tight text-white sm:text-6xl font-sans mb-6">
          Investigate codebases like a{' '}
          <span className="bg-gradient-to-r from-brand-400 via-brand-500 to-indigo-400 bg-clip-text text-transparent">
            Senior Engineer
          </span>
        </h1>
        <p className="text-lg text-dark-300 leading-relaxed">
          Paste any public GitHub repository link below. Our multi-agent AI system analyzes the files, imports, and structures dynamically to help you reason over code in real-time.
        </p>

        {/* Input Form */}
        <form onSubmit={handleSubmit} className="mt-10 relative">
          <div className="flex flex-col sm:flex-row gap-3 rounded-2xl border border-dark-800 bg-dark-900/60 p-2 backdrop-blur-md focus-within:border-brand-500/50 focus-within:ring-2 focus-within:ring-brand-500/10 transition-all duration-300">
            <div className="relative flex-1 flex items-center px-3">
              <Search className="h-5 w-5 text-dark-400 mr-2 flex-shrink-0" />
              <input
                type="text"
                placeholder="https://github.com/owner/repository"
                value={url}
                onChange={(e) => setUrl(e.target.value)}
                className="w-full bg-transparent py-3 text-sm text-white placeholder-dark-500 focus:outline-none"
              />
            </div>
            <button
              type="submit"
              disabled={isLoading}
              className="flex items-center justify-center gap-2 rounded-xl bg-brand-600 px-6 py-3.5 text-sm font-semibold text-white shadow-lg shadow-brand-600/30 hover:bg-brand-500 hover:shadow-brand-500/40 focus:outline-none transition-all duration-300 disabled:opacity-70"
            >
              {isLoading ? (
                <>
                  <Loader2 className="h-4 w-4 animate-spin" />
                  <span>Scanning Codebase...</span>
                </>
              ) : (
                <>
                  <span>Analyze Repo</span>
                  <ArrowRight className="h-4 w-4" />
                </>
              )}
            </button>
          </div>
          {error && <p className="mt-2 text-left text-xs text-rose-400 pl-4">{error}</p>}
        </form>
      </div>

      {/* Grid List Section */}
      <div>
        <h2 className="text-xl font-bold text-white mb-6 flex items-center gap-2">
          <Layers className="h-5 w-5 text-brand-400" />
          <span>Analyzed Repositories</span>
        </h2>

        {repos.length === 0 ? (
          <div className="text-center py-20 rounded-2xl border border-dashed border-dark-800 bg-dark-900/20">
            <Layers className="h-10 w-10 text-dark-500 mx-auto mb-4" />
            <p className="text-dark-400 text-sm">No repositories analyzed yet. Submit a link above to get started.</p>
          </div>
        ) : (
          <div className="grid gap-6 sm:grid-cols-2 lg:grid-cols-3">
            {repos.map((repo) => (
              <div
                key={repo.id}
                onClick={() => onSelectRepo(repo)}
                className="group relative flex flex-col justify-between overflow-hidden rounded-2xl border border-dark-800 bg-dark-900/40 p-6 cursor-pointer hover:border-dark-700/60 hover:bg-dark-900/60 transition-all duration-300 hover:shadow-xl hover:shadow-brand-500/[0.02]"
              >
                <div>
                  {/* Title & Stars */}
                  <div className="flex items-start justify-between mb-3">
                    <h3 className="font-bold text-white group-hover:text-brand-300 transition-colors text-lg truncate pr-4">
                      {repo.name}
                    </h3>
                    <div className="flex items-center gap-1 text-xs text-dark-400 bg-dark-950/80 px-2 py-0.5 rounded-full border border-dark-850">
                      <Star className="h-3.5 w-3.5 text-amber-500 fill-amber-500" />
                      <span>Repo</span>
                    </div>
                  </div>
                  <p className="text-xs text-brand-400 font-semibold mb-3">{repo.owner}</p>
                  
                  {/* Framework Badges */}
                  {repo.frameworks && repo.frameworks.length > 0 && (
                    <div className="flex flex-wrap gap-1.5 mb-4">
                      {repo.frameworks.map((f, idx) => (
                        <span key={idx} className="text-[10px] font-medium bg-brand-500/10 text-brand-300 border border-brand-500/15 px-2 py-0.5 rounded">
                          {f}
                        </span>
                      ))}
                    </div>
                  )}
                </div>

                <div>
                  {/* Languages Progress bar */}
                  {repo.languages && Object.keys(repo.languages).length > 0 && (
                    <div className="mb-4">
                      <div className="flex h-1.5 w-full overflow-hidden rounded-full bg-dark-800">
                        {Object.entries(repo.languages).slice(0, 4).map(([lang, val], idx, arr) => {
                          const total = Object.values(repo.languages).reduce((a, b) => a + b, 0);
                          const pct = (val / total) * 100;
                          return (
                            <div
                              key={lang}
                              style={{
                                width: `${pct}%`,
                                backgroundColor: getLanguageColor(lang)
                              }}
                              className="h-full"
                              title={`${lang}: ${pct.toFixed(1)}%`}
                            />
                          );
                        })}
                      </div>
                      <div className="mt-2 flex flex-wrap gap-x-3 gap-y-1">
                        {Object.entries(repo.languages).slice(0, 3).map(([lang, val]) => {
                          const total = Object.values(repo.languages).reduce((a, b) => a + b, 0);
                          const pct = (val / total) * 100;
                          return (
                            <div key={lang} className="flex items-center gap-1.5 text-[10px] text-dark-400">
                              <span
                                className="h-2 w-2 rounded-full"
                                style={{ backgroundColor: getLanguageColor(lang) }}
                              />
                              <span>{lang} ({pct.toFixed(0)}%)</span>
                            </div>
                          );
                        })}
                      </div>
                    </div>
                  )}

                  <div className="border-t border-dark-800/80 pt-4 flex items-center justify-between text-xs text-dark-400">
                    <span>Registered in platform</span>
                    <span className="text-brand-400 group-hover:translate-x-1 transition-transform inline-flex items-center gap-1">
                      <span>Explore</span>
                      <ArrowRight className="h-3.5 w-3.5" />
                    </span>
                  </div>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
