import React from 'react';
import { Plus, MessageSquare, Trash2, Clock, ChevronRight } from 'lucide-react';

export default function ChatHistory({ sessions, activeSessionId, onSelectSession, onNewSession, onDeleteSession }) {

  const formatDate = (dateStr) => {
    const date = new Date(dateStr);
    const now = new Date();
    const diffMs = now - date;
    const diffMins = Math.floor(diffMs / 60000);
    const diffHours = Math.floor(diffMs / 3600000);
    const diffDays = Math.floor(diffMs / 86400000);

    if (diffMins < 1) return 'Just now';
    if (diffMins < 60) return `${diffMins}m ago`;
    if (diffHours < 24) return `${diffHours}h ago`;
    if (diffDays < 7) return `${diffDays}d ago`;
    return date.toLocaleDateString();
  };

  return (
    <div className="flex flex-col h-full min-h-0">
      {/* New Chat Button */}
      <div className="p-3 border-b border-dark-800/60">
        <button
          onClick={onNewSession}
          className="w-full flex items-center justify-center gap-2 px-4 py-2.5 rounded-xl bg-brand-600 text-white text-xs font-bold hover:bg-brand-500 hover:shadow-lg hover:shadow-brand-500/20 transition-all"
        >
          <Plus className="h-3.5 w-3.5" />
          <span>New Chat</span>
        </button>
      </div>

      {/* Session List */}
      <div className="flex-1 overflow-y-auto px-2 py-2 space-y-1 custom-scrollbar">
        {sessions.length === 0 ? (
          <div className="text-center py-8 px-3">
            <MessageSquare className="h-6 w-6 text-dark-600 mx-auto mb-2" />
            <p className="text-[11px] text-dark-500">No conversations yet.<br />Start a new chat to begin.</p>
          </div>
        ) : (
          sessions.map((session) => {
            const isActive = session.id === activeSessionId;
            return (
              <div
                key={session.id}
                className={`group relative flex items-center gap-2 px-3 py-2.5 rounded-xl cursor-pointer transition-all text-left ${
                  isActive
                    ? 'bg-brand-500/10 border border-brand-500/20 text-brand-200'
                    : 'hover:bg-dark-800/50 text-dark-300 border border-transparent'
                }`}
                onClick={() => onSelectSession(session)}
              >
                <div className="flex-shrink-0">
                  <div className={`h-7 w-7 rounded-lg flex items-center justify-center ${
                    isActive ? 'bg-brand-500/20' : 'bg-dark-800/60'
                  }`}>
                    <MessageSquare className={`h-3.5 w-3.5 ${isActive ? 'text-brand-400' : 'text-dark-500'}`} />
                  </div>
                </div>

                <div className="flex-1 min-w-0">
                  <div className={`text-[11px] font-semibold truncate ${isActive ? 'text-white' : 'text-dark-200'}`}>
                    {session.title}
                  </div>
                  <div className="flex items-center gap-2 mt-0.5">
                    <span className="text-[9px] text-dark-500 flex items-center gap-0.5">
                      <Clock className="h-2.5 w-2.5" />
                      {formatDate(session.created_at)}
                    </span>
                    {session.message_count > 0 && (
                      <span className="text-[9px] text-dark-500">
                        {session.message_count} msg{session.message_count !== 1 ? 's' : ''}
                      </span>
                    )}
                  </div>
                </div>

                {/* Delete button — visible on hover */}
                <button
                  onClick={(e) => {
                    e.stopPropagation();
                    onDeleteSession(session.id);
                  }}
                  className="opacity-0 group-hover:opacity-100 flex-shrink-0 p-1.5 rounded-lg hover:bg-red-500/20 text-dark-500 hover:text-red-400 transition-all"
                  title="Delete this chat"
                >
                  <Trash2 className="h-3 w-3" />
                </button>
              </div>
            );
          })
        )}
      </div>
    </div>
  );
}
