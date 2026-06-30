import React from 'react';
import { Terminal, Brain, GitBranch, ShieldCheck } from 'lucide-react';

export default function Navbar({ activeRepo, onBack }) {
  return (
    <header className="sticky top-0 z-50 w-full border-b border-dark-800 bg-dark-950/80 backdrop-blur-md">
      <div className="mx-auto flex max-w-7xl h-16 items-center justify-between px-6">
        <div className="flex items-center gap-3 cursor-pointer" onClick={onBack}>
          <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-gradient-to-tr from-brand-600 to-indigo-500 shadow-lg shadow-brand-500/25">
            <Brain className="h-5 w-5 text-white" />
          </div>
          <span className="text-xl font-bold tracking-tight text-white font-sans">
            RepoMind <span className="bg-gradient-to-r from-brand-400 to-indigo-400 bg-clip-text text-transparent">AI</span>
          </span>
        </div>

        {activeRepo && (
          <div className="hidden md:flex items-center gap-3 bg-dark-900/80 border border-dark-800 px-4 py-1.5 rounded-full text-xs text-dark-300">
            <GitBranch className="h-3.5 w-3.5 text-brand-400" />
            <span className="font-semibold text-dark-100">{activeRepo.owner} / {activeRepo.name}</span>
            <span className="h-3 w-px bg-dark-800"></span>
            <span className="text-brand-300 bg-brand-500/10 px-2 py-0.5 rounded-full">Autonomous Platform</span>
          </div>
        )}

        <div className="flex items-center gap-4">
          <div className="flex items-center gap-2 text-xs text-emerald-400 bg-emerald-500/10 px-3 py-1 rounded-full border border-emerald-500/20">
            <ShieldCheck className="h-3.5 w-3.5" />
            <span>Agent Server Active</span>
          </div>
        </div>
      </div>
    </header>
  );
}
