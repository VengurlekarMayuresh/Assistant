import React, { useState, useEffect, useRef } from 'react';
import mermaid from 'mermaid';
import axios from 'axios';
import { Compass, Loader2, Maximize, ZoomIn, ZoomOut } from 'lucide-react';
import { TransformWrapper, TransformComponent } from 'react-zoom-pan-pinch';

mermaid.initialize({
  startOnLoad: true,
  theme: 'dark',
  securityLevel: 'loose',
});

export default function ArchitectureMap({ repoId, onNodeClick }) {
  const [diagram, setDiagram] = useState('');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const containerRef = useRef(null);

  const [svgStr, setSvgStr] = useState('');

  useEffect(() => {
    if (!repoId) return;

    const fetchArchitecture = async () => {
      setLoading(true);
      setError(null);
      setSvgStr('');
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
    if (diagram && !loading && !error) {
      const renderDiagram = async () => {
        try {
          const id = `mermaid-graph-${Math.round(Math.random() * 100000)}`;
          const { svg } = await mermaid.render(id, diagram);
          setSvgStr(svg);
        } catch (err) {
          console.error("Mermaid parsing error:", err);
          setError("Generated diagram contains invalid syntax.");
        }
      };
      renderDiagram();
    }
  }, [diagram, loading, error]);

  useEffect(() => {
    if (svgStr && containerRef.current) {
      const nodes = containerRef.current.querySelectorAll('.node');
      
      const handleClick = (e) => {
        let path = e.currentTarget.id;
        // Remove common mermaid auto-generated prefixes
        path = path.replace(/^flowchart-/, '');
        // Remove mermaid auto-generated suffixes (e.g. -123)
        path = path.replace(/-\d+$/, '');
        // Remove any surrounding quotes
        path = path.replace(/"/g, '');
        // Sometimes Mermaid uses a different prefix in newer versions like `node-`
        path = path.replace(/^node-/, '');
        
        console.log("Clicked Node Extracted Path:", path); // for debugging in browser console
        
        if (onNodeClick) {
          onNodeClick(path);
        }
      };

      nodes.forEach(node => {
        node.style.cursor = 'pointer';
        node.addEventListener('click', handleClick);
      });

      return () => {
        nodes.forEach(node => {
          node.removeEventListener('click', handleClick);
        });
      };
    }
  }, [svgStr, onNodeClick]);

  if (loading) {
    return (
      <div className="w-full h-[72vh] min-h-[560px] bg-dark-950/20 rounded-2xl border border-dark-800/80 flex flex-col items-center justify-center text-center">
        <Loader2 className="h-8 w-8 text-brand-500 animate-spin mb-4" />
        <div className="text-sm font-semibold text-white">Generating AI Architecture Map...</div>
        <div className="text-xs text-dark-400 mt-2">Analyzing files, languages, and frameworks using Gemini.</div>
      </div>
    );
  }

  if (error || !diagram || (!svgStr && !loading && !error)) {
    return (
      <div className="w-full h-[72vh] min-h-[560px] bg-dark-950/20 rounded-2xl border border-dark-800/80 flex items-center justify-center text-center px-6">
        <div>
          <div className="text-sm font-semibold text-red-400">{error || "Diagram unavailable"}</div>
          <div className="text-xs text-dark-400 mt-2">Check the backend logs for details.</div>
          {diagram && <div className="text-xs text-dark-500 mt-4 text-left p-4 bg-dark-900 rounded overflow-auto max-h-40 whitespace-pre">{diagram}</div>}
        </div>
      </div>
    );
  }

  return (
    <div className="w-full h-[72vh] min-h-[560px] max-h-[780px] bg-dark-950/20 rounded-2xl overflow-hidden relative border border-dark-800/80 flex justify-center items-center">
      <div className="absolute top-4 left-4 z-10 bg-dark-900/90 border border-dark-800 px-3.5 py-1.5 rounded-lg shadow-lg">
        <span className="text-[10px] font-bold text-brand-300 uppercase tracking-wider flex items-center gap-1.5">
          <Compass className="h-3.5 w-3.5 text-brand-500" />
          Interactive Architecture Map
        </span>
      </div>
      
      <TransformWrapper
        initialScale={1}
        minScale={0.1}
        maxScale={4}
        centerOnInit={true}
        wheel={{ step: 0.05 }} // removed smoothStep as it can cause erratic scroll in some browsers
        pinch={{ step: 5 }}
      >
        {({ zoomIn, zoomOut, resetTransform }) => (
          <>
            <div className="absolute bottom-4 right-4 z-10 flex gap-2">
              <button onClick={() => zoomIn()} className="p-2 bg-dark-900 border border-dark-800 rounded shadow hover:bg-dark-800 transition-colors">
                <ZoomIn className="h-4 w-4 text-dark-300" />
              </button>
              <button onClick={() => zoomOut()} className="p-2 bg-dark-900 border border-dark-800 rounded shadow hover:bg-dark-800 transition-colors">
                <ZoomOut className="h-4 w-4 text-dark-300" />
              </button>
              <button onClick={() => resetTransform()} className="p-2 bg-dark-900 border border-dark-800 rounded shadow hover:bg-dark-800 transition-colors">
                <Maximize className="h-4 w-4 text-dark-300" />
              </button>
            </div>
            
            <TransformComponent wrapperStyle={{ width: "100%", height: "100%" }} contentStyle={{ width: "100%", height: "100%", display: "flex", justifyContent: "center", alignItems: "center" }}>
              <div 
                ref={containerRef}
                className="mermaid-container w-full flex justify-center items-center"
                dangerouslySetInnerHTML={{ __html: svgStr }}
              />
            </TransformComponent>
          </>
        )}
      </TransformWrapper>
    </div>
  );
}

