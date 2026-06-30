import React, { useMemo } from 'react';
import { ReactFlow, Background, Controls } from '@xyflow/react';
import { Folder, FileCode, Cpu } from 'lucide-react';
import '@xyflow/react/dist/style.css';

export default function ArchitectureMap({ structure }) {
  const treeItems = structure?.tree || [];

  const { nodes, edges } = useMemo(() => {
    if (treeItems.length === 0) {
      return { nodes: [], edges: [] };
    }

    // Filter to limit diagram complexity (max 35 nodes, depth <= 3)
    const filteredItems = treeItems
      .filter((item) => {
        const parts = item.path.split('/');
        // Keep files/folders up to depth 3
        if (parts.length > 3) return false;
        
        // Exclude test configs, lock files, git, images, hidden files
        if (
          item.path.startsWith('.') || 
          item.path.includes('node_modules') || 
          item.path.includes('__pycache__') ||
          item.path.endsWith('.png') ||
          item.path.endsWith('.ico')
        ) return false;
        
        return true;
      })
      .slice(0, 35); // Hard cap for visual aesthetics

    const nodesList = [];
    const edgesList = [];

    // 1. Create Root Node
    nodesList.push({
      id: 'root',
      position: { x: 250, y: 0 },
      data: {
        label: (
          <div className="flex items-center gap-2 font-bold text-white text-xs">
            <Cpu className="h-4 w-4 text-brand-400" />
            <span>Codebase Root</span>
          </div>
        )
      },
      style: {
        background: 'rgba(83, 86, 250, 0.15)',
        border: '1.5px solid rgba(83, 86, 250, 0.4)',
        boxShadow: '0 0 15px rgba(83, 86, 250, 0.25)',
        width: 150
      }
    });

    // Tracking coordinate placement
    const depthMap = {}; // depth -> count of nodes at this depth

    // Process nodes
    filteredItems.forEach((item) => {
      const parts = item.path.split('/');
      const depth = parts.length;
      const isDir = item.type === 'tree';
      const name = parts[parts.length - 1];

      // Calculate position
      if (!depthMap[depth]) depthMap[depth] = 0;
      const index = depthMap[depth];
      depthMap[depth]++;

      // Spacing layout math
      const x = 50 + index * 240;
      const y = depth * 130;

      // Styling parameters
      const nodeColor = isDir ? 'border-brand-500/30 bg-brand-500/5' : 'border-dark-800 bg-dark-900/90';
      const Icon = isDir ? Folder : FileCode;
      const iconColor = isDir ? 'text-brand-400' : 'text-indigo-400';

      nodesList.push({
        id: item.path,
        position: { x, y },
        data: {
          label: (
            <div className="flex items-center gap-2">
              <Icon className={`h-4 w-4 ${iconColor} flex-shrink-0`} />
              <div className="text-xs font-mono truncate max-w-[150px]" title={item.path}>
                {name}
              </div>
            </div>
          )
        },
        className: nodeColor,
        style: {
          width: 180,
          padding: '10px 14px'
        }
      });

      // 2. Connect Edges
      if (depth === 1) {
        // Connect directly to root
        edgesList.push({
          id: `root-${item.path}`,
          source: 'root',
          target: item.path,
          animated: isDir
        });
      } else {
        // Connect to parent folder
        const parentPath = parts.slice(0, -1).join('/');
        // Verify if parent node actually exists in our visual nodes list
        const parentExists = filteredItems.some(i => i.path === parentPath);
        
        edgesList.push({
          id: `${parentExists ? parentPath : 'root'}-${item.path}`,
          source: parentExists ? parentPath : 'root',
          target: item.path,
          animated: isDir
        });
      }
    });

    return { nodes: nodesList, edges: edgesList };
  }, [treeItems]);

  if (treeItems.length === 0) {
    return (
      <div className="h-full min-h-[420px] w-full bg-dark-950/20 rounded-2xl overflow-hidden relative border border-dark-800/80 flex items-center justify-center px-6 text-center">
        <div>
          <div className="text-sm font-semibold text-white">Architecture map unavailable for this repository.</div>
          <div className="text-xs text-dark-400 mt-2">No repository tree was returned by the backend scan yet. Re-sync the repository and reopen this view.</div>
        </div>
      </div>
    );
  }

  return (
    <div className="h-full min-h-[420px] w-full bg-dark-950/20 rounded-2xl overflow-hidden relative border border-dark-800/80">
      <div className="absolute top-4 left-4 z-10 bg-dark-900/90 border border-dark-800 px-3.5 py-1.5 rounded-lg shadow-lg">
        <span className="text-[10px] font-bold text-dark-300 uppercase tracking-wider flex items-center gap-1.5">
          <span className="h-1.5 w-1.5 rounded-full bg-brand-500 animate-pulse" />
          Interactive Codebase Map
        </span>
      </div>

      <div className="h-full w-full">
        <ReactFlow
          nodes={nodes}
          edges={edges}
          fitView
          minZoom={0.2}
          maxZoom={1.5}
          proOptions={{ hideAttribution: true }}
        >
          <Background color="#1e293b" gap={16} size={1} />
          <Controls />
        </ReactFlow>
      </div>
    </div>
  );
}
