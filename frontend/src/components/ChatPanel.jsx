import React, { useState, useEffect, useRef } from 'react';
import { Send, Terminal as TermIcon, CheckCircle2, Circle, Loader2, Sparkles, AlertCircle } from 'lucide-react';

export default function ChatPanel({ sessionId, messages, setMessages, activeRepo }) {
  const [input, setInput] = useState('');
  const [logs, setLogs] = useState([]);
  const [plan, setPlan] = useState([]);
  const [currentStep, setCurrentStep] = useState(-1);
  const [isAgentRunning, setIsAgentRunning] = useState(false);
  const [showLogs, setShowLogs] = useState(true);
  
  const wsRef = useRef(null);
  const messagesEndRef = useRef(null);
  const logsEndRef = useRef(null);

  // Auto scroll to bottom
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, isAgentRunning]);

  useEffect(() => {
    logsEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [logs]);

  // Load existing logs and messages for this session
  useEffect(() => {
    setLogs([]);
    setPlan([]);
    setCurrentStep(-1);
    setIsAgentRunning(false);

    // Fetch historic logs
    fetch(`http://localhost:8000/api/sessions/${sessionId}/logs`)
      .then((res) => res.json())
      .then((data) => {
        const formattedLogs = data.map(log => ({
          agent: log.agent_name,
          action: log.action_type,
          message: log.message,
          timestamp: new Date(log.created_at).toLocaleTimeString()
        }));
        setLogs(formattedLogs);

        // Recover latest plan if any exists in history
        const planLog = data.reverse().find(log => log.action_type === 'plan');
        if (planLog && planLog.data && planLog.data.plan) {
          setPlan(planLog.data.plan);
        }
      })
      .catch(err => console.error("Error loading historic logs", err));

    // Establish WebSocket Connection
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsUrl = `${protocol}//localhost:8000/api/sessions/${sessionId}/chat`;
    const ws = new WebSocket(wsUrl);

    ws.onopen = () => {
      console.log("WebSocket connected successfully.");
    };

    ws.onmessage = (event) => {
      const data = JSON.parse(event.data);

      if (data.type === 'log') {
        const timestamp = new Date().toLocaleTimeString();
        setLogs((prev) => [...prev, {
          agent: data.agent,
          action: data.action,
          message: data.message,
          timestamp
        }]);

        if (data.action === 'plan' && data.data && data.data.plan) {
          setPlan(data.data.plan);
          setCurrentStep(0);
        }

        if (data.agent === 'Explorer' && data.data && typeof data.data.step_index === 'number') {
          setCurrentStep(data.data.step_index);
        }
      } 
      else if (data.type === 'message') {
        setIsAgentRunning(false);
        setMessages((prev) => [...prev, {
          id: Date.now(),
          role: data.role,
          content: data.content
        }]);
      } 
      else if (data.type === 'error') {
        setIsAgentRunning(false);
        setLogs((prev) => [...prev, {
          agent: 'System',
          action: 'error',
          message: data.message,
          timestamp: new Date().toLocaleTimeString()
        }]);
      }
    };

    ws.onclose = () => {
      console.log("WebSocket closed.");
      setIsAgentRunning(false);
    };

    wsRef.current = ws;

    return () => {
      ws.close();
    };
  }, [sessionId]);

  const handleSendMessage = (e) => {
    e.preventDefault();
    if (!input.trim() || isAgentRunning) return;

    const query = input.trim();
    
    // Add user message locally
    setMessages((prev) => [...prev, {
      id: Date.now(),
      role: 'user',
      content: query
    }]);

    setInput('');
    setIsAgentRunning(true);
    
    // Send to agent server via WebSocket
    if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({ content: query }));
    } else {
      setIsAgentRunning(false);
      alert("Socket connection is closed. Please try reloading the page.");
    }
  };

  // Helper to render inline markdown
  const renderInlineMarkdown = (text) => {
    const escapeHTML = (str) => str.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
    let html = escapeHTML(text);
    html = html.replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>');
    html = html.replace(/`(.*?)`/g, '<code class="bg-dark-950/80 border border-dark-800 text-brand-300 px-1 py-0.5 rounded font-mono text-[11px]">$1</code>');
    return <span dangerouslySetInnerHTML={{ __html: html }} />;
  };

  // Helper to parse markdown paragraphs & codeblocks
  const renderMarkdown = (text) => {
    if (!text) return null;
    const parts = text.split(/(```[\s\S]*?```)/g);
    
    return parts.map((part, idx) => {
      if (part.startsWith('```')) {
        const lines = part.split('\n');
        const header = lines[0].replace('```', '').trim();
        const code = lines.slice(1, -1).join('\n');
        return (
          <div key={idx} className="my-3 rounded-xl border border-dark-800 bg-dark-950 font-mono text-xs text-dark-200 overflow-hidden shadow-inner">
            <div className="bg-dark-900/60 border-b border-dark-850 px-4 py-2 flex justify-between items-center text-[10px] text-dark-400">
              <span>{header || 'code'}</span>
            </div>
            <pre className="p-4 overflow-x-auto whitespace-pre font-mono"><code>{code}</code></pre>
          </div>
        );
      }
      
      const lines = part.split('\n');
      return lines.map((line, lIdx) => {
        const trimmed = line.trim();
        if (trimmed.startsWith('# ')) {
          return <h1 key={`${idx}-${lIdx}`} className="text-xl font-bold text-white mt-4 mb-2 first:mt-0 font-sans border-b border-dark-800 pb-1">{trimmed.slice(2)}</h1>;
        }
        if (trimmed.startsWith('## ')) {
          return <h2 key={`${idx}-${lIdx}`} className="text-lg font-bold text-white mt-4 mb-2 first:mt-0 font-sans">{trimmed.slice(3)}</h2>;
        }
        if (trimmed.startsWith('### ')) {
          return <h3 key={`${idx}-${lIdx}`} className="text-base font-bold text-white mt-3 mb-1 font-sans">{trimmed.slice(4)}</h3>;
        }
        if (trimmed.startsWith('- ') || trimmed.startsWith('* ')) {
          return (
            <li key={`${idx}-${lIdx}`} className="ml-5 list-disc text-sm text-dark-200 my-1.5 leading-relaxed">
              {renderInlineMarkdown(trimmed.slice(2))}
            </li>
          );
        }
        if (trimmed === '') return <div key={`${idx}-${lIdx}`} className="h-2" />;
        return (
          <p key={`${idx}-${lIdx}`} className="text-sm text-dark-200 leading-relaxed my-2">
            {renderInlineMarkdown(line)}
          </p>
        );
      });
    });
  };

  return (
    <div className="flex flex-col h-full bg-dark-900/30">
      
      {/* Workspace Area: Messages + Agent status */}
      <div className="flex-1 overflow-y-auto px-6 py-6 space-y-6">
        {messages.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-full text-center max-w-md mx-auto pt-20">
            <div className="h-12 w-12 rounded-2xl bg-brand-500/10 border border-brand-500/20 flex items-center justify-center text-brand-400 mb-4 animate-pulse">
              <Sparkles className="h-6 w-6" />
            </div>
            <h3 className="text-white font-bold text-base mb-2">Start your investigation</h3>
            <p className="text-dark-400 text-xs leading-relaxed">
              Ask anything about the codebase. e.g., <br />
              <code className="text-brand-300 font-mono mt-1 inline-block text-[11px]">"Explain how routing is set up"</code> or <br />
              <code className="text-brand-300 font-mono mt-1 inline-block text-[11px]">"Where does the application read configurations?"</code>
            </p>
          </div>
        ) : (
          messages.map((msg) => (
            <div
              key={msg.id}
              className={`flex flex-col ${msg.role === 'user' ? 'items-end' : 'items-start'}`}
            >
              <div
                className={`max-w-[85%] rounded-2xl p-4 text-left border ${
                  msg.role === 'user'
                    ? 'bg-brand-600 text-white border-brand-500/20 shadow-md shadow-brand-600/10 rounded-tr-none'
                    : 'bg-dark-900/80 text-dark-100 border-dark-800/80 rounded-tl-none'
                }`}
              >
                <div className="text-[10px] font-semibold tracking-wider text-dark-400 mb-1.5">
                  {msg.role === 'user' ? 'DEVELOPER' : 'REPOMIND AGENT'}
                </div>
                <div className="text-sm">
                  {msg.role === 'user' ? (
                    <p className="whitespace-pre-line leading-relaxed">{msg.content}</p>
                  ) : (
                    renderMarkdown(msg.content)
                  )}
                </div>
              </div>
            </div>
          ))
        )}

        {/* Live Agent Executing Card */}
        {isAgentRunning && (
          <div className="rounded-2xl border border-dark-800 bg-dark-900/50 p-5 space-y-4 shadow-lg backdrop-blur-md">
            <div className="flex items-center justify-between border-b border-dark-800 pb-3">
              <div className="flex items-center gap-2">
                <Loader2 className="h-4 w-4 text-brand-400 animate-spin" />
                <span className="text-xs font-bold text-white tracking-wide">AGENT WORKFLOW RUNNING</span>
              </div>
              <button
                onClick={() => setShowLogs(!showLogs)}
                className="text-[10px] font-semibold text-brand-400 hover:text-brand-300 hover:underline flex items-center gap-1.5"
              >
                <TermIcon className="h-3 w-3" />
                <span>{showLogs ? 'Hide Console' : 'Show Console'}</span>
              </button>
            </div>

            {/* Plan Checklist */}
            {plan.length > 0 && (
              <div className="space-y-2.5">
                <div className="text-[10px] font-bold text-dark-400 tracking-wider">INVESTIGATION CHECKLIST</div>
                <div className="grid gap-2">
                  {plan.map((step, idx) => {
                    const isCompleted = idx < currentStep;
                    const isActive = idx === currentStep;
                    return (
                      <div
                        key={idx}
                        className={`flex items-start gap-2.5 rounded-lg p-2.5 text-xs border ${
                          isActive
                            ? 'bg-brand-500/10 border-brand-500/25 text-brand-200'
                            : isCompleted
                            ? 'bg-dark-950/40 border-dark-850 text-dark-400'
                            : 'bg-dark-950/20 border-transparent text-dark-500'
                        }`}
                      >
                        {isCompleted ? (
                          <CheckCircle2 className="h-4 w-4 text-emerald-400 mt-0.5 flex-shrink-0" />
                        ) : isActive ? (
                          <Loader2 className="h-4 w-4 text-brand-400 animate-spin mt-0.5 flex-shrink-0" />
                        ) : (
                          <Circle className="h-4 w-4 text-dark-700 mt-0.5 flex-shrink-0" />
                        )}
                        <div className="font-medium leading-tight">{step}</div>
                      </div>
                    );
                  })}
                </div>
              </div>
            )}

            {/* Logs console */}
            {showLogs && logs.length > 0 && (
              <div className="space-y-1.5">
                <div className="text-[10px] font-bold text-dark-400 tracking-wider">OPERATIONS TERMINAL</div>
                <div className="h-40 overflow-y-auto rounded-xl bg-dark-950 p-4 font-mono text-[10px] text-dark-300 border border-dark-850 flex flex-col gap-1.5 shadow-inner">
                  {logs.map((log, idx) => (
                    <div key={idx} className="leading-relaxed">
                      <span className="text-dark-500">[{log.timestamp}]</span>{' '}
                      <span className={`${log.action === 'error' ? 'text-rose-400' : 'text-indigo-400'}`}>
                        {log.agent}
                      </span>
                      <span className="text-dark-400">:</span>{' '}
                      <span className={log.action === 'error' ? 'text-rose-300' : 'text-dark-200'}>
                        {log.message}
                      </span>
                    </div>
                  ))}
                  <div ref={logsEndRef} />
                </div>
              </div>
            )}
          </div>
        )}
        <div ref={messagesEndRef} />
      </div>

      {/* Input Tray */}
      <div className="p-4 border-t border-dark-800/80 bg-dark-950/40 backdrop-blur-md">
        <form onSubmit={handleSendMessage} className="flex gap-2 max-w-5xl mx-auto">
          <input
            type="text"
            placeholder="Ask a question about the repository..."
            value={input}
            onChange={(e) => setInput(e.target.value)}
            disabled={isAgentRunning}
            className="flex-1 rounded-xl border border-dark-800 bg-dark-900/60 px-4 py-3.5 text-sm text-white placeholder-dark-500 focus:outline-none focus:border-brand-500/50 transition-all disabled:opacity-60"
          />
          <button
            type="submit"
            disabled={!input.trim() || isAgentRunning}
            className="flex h-12 w-12 items-center justify-center rounded-xl bg-brand-600 text-white hover:bg-brand-500 hover:shadow-lg hover:shadow-brand-500/20 focus:outline-none transition-all disabled:opacity-50 disabled:hover:shadow-none"
          >
            {isAgentRunning ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <Send className="h-4 w-4" />
            )}
          </button>
        </form>
      </div>

    </div>
  );
}
