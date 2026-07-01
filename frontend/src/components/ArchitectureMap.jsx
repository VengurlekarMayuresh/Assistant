import React, { useState, useEffect, useRef } from 'react';
import mermaid from 'mermaid';
import axios from 'axios';
import { Compass, Loader2 } from 'lucide-react';

mermaid.initialize({
  startOnLoad: true,
  theme: 'dark',
  securityLevel: 'loose',
});

export default function ArchitectureMap({ repoId }) {
  const [diagram, setDiagram] = useState('');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const containerRef = useRef(null);

  useEffect(() => {
    if (!repoId) return;

    const fetchArchitecture = async () => {
      setLoading(true);
      setError(null);
      try {
        const response = await axios.get(`http://localhost:8000/api/repositories/${repoId}/architecture`);
        setDiagram(response.data.mermaid);
      } catch (err) {
        console.error('Failed to fetch architecture diagram:', err);
        setError('Failed to generate architecture diagram.');
      } finally {
        setLoading(false);
      }
    };

    fetchArchitecture();
  }, [repoId]);

  useEffect(() => {
    if (diagram && containerRef.current && !loading && !error) {
      mermaid.contentLoaded();
    }
  }, [diagram, loading, error]);

  if (loading) {
    return (
      <div className="w-full h-[72vh] min-h-[560px] bg-dark-950/20 rounded-2xl border border-dark-800/80 flex flex-col items-center justify-center text-center">
        <Loader2 className="h-8 w-8 text-brand-500 animate-spin mb-4" />
        <div className="text-sm font-semibold text-white">Generating AI Architecture Map...</div>
        <div className="text-xs text-dark-400 mt-2">Analyzing files, languages, and frameworks using Gemini.</div>
      </div>
    );
  }

  if (error || !diagram) {
    return (
      <div className="w-full h-[72vh] min-h-[560px] bg-dark-950/20 rounded-2xl border border-dark-800/80 flex items-center justify-center text-center px-6">
        <div>
          <div className="text-sm font-semibold text-red-400">{error || "Diagram unavailable"}</div>
          <div className="text-xs text-dark-400 mt-2">Check the backend logs for details.</div>
        </div>
      </div>
    );
  }

  return (
    <div className="w-full h-[72vh] min-h-[560px] max-h-[780px] bg-dark-950/20 rounded-2xl overflow-auto relative border border-dark-800/80 p-6 flex justify-center items-start">
      <div className="absolute top-4 left-4 z-10 bg-dark-900/90 border border-dark-800 px-3.5 py-1.5 rounded-lg shadow-lg">
        <span className="text-[10px] font-bold text-brand-300 uppercase tracking-wider flex items-center gap-1.5">
          <Compass className="h-3.5 w-3.5 text-brand-500" />
          GitDiagram Architecture
        </span>
      </div>
      
      <div 
        ref={containerRef}
        className="mermaid mt-12 bg-white/5 p-8 rounded-xl w-full flex justify-center"
      >
        {diagram}
      </div>
    </div>
  );
}

