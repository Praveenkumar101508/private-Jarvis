"use client";

import { useState, useRef } from "react";
import { Shield, GraduationCap, Bot, ChevronLeft, ChevronRight, Clock, Download, HardDrive, Upload, RefreshCw } from "lucide-react";
import clsx from "clsx";

export type AppMode = "assistant" | "tutor" | "bodyguard";

interface ConversationItem {
  id: string;
  title: string;
  preview: string;
  timestamp: Date;
}

interface Props {
  mode: AppMode;
  onModeChange: (mode: AppMode) => void;
  onNewChat: () => void;
  recentChats?: ConversationItem[];
  token?: string;
}

const MODES: { id: AppMode; label: string; icon: React.ReactNode; accent: string; description: string }[] = [
  {
    id: "assistant",
    label: "Assistant",
    icon: <Bot className="w-4 h-4" />,
    accent: "text-saffron-400 border-saffron-500/60 bg-saffron-500/10",
    description: "General AI assistant",
  },
  {
    id: "tutor",
    label: "Tutor",
    icon: <GraduationCap className="w-4 h-4" />,
    accent: "text-indigo-400 border-indigo-500/60 bg-indigo-500/10",
    description: "Socratic learning mode",
  },
  {
    id: "bodyguard",
    label: "Bodyguard",
    icon: <Shield className="w-4 h-4" />,
    accent: "text-red-400 border-red-500/60 bg-red-500/10",
    description: "Security monitoring",
  },
];

function formatRelative(date: Date): string {
  const now = Date.now();
  const diff = now - date.getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 1) return "now";
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  return `${Math.floor(hrs / 24)}d ago`;
}

export default function Sidebar({ mode, onModeChange, onNewChat, recentChats = [], token = "" }: Props) {
  const [collapsed, setCollapsed] = useState(false);
  const [backupStatus, setBackupStatus] = useState<string>("");
  const [backupLoading, setBackupLoading] = useState(false);
  const restoreInputRef = useRef<HTMLInputElement>(null);

  const authHeaders = { Authorization: `Bearer ${token}` };

  const triggerBackup = async () => {
    setBackupLoading(true);
    setBackupStatus("Creating backup…");
    try {
      const res = await fetch("/api/v1/backup/create", { method: "POST", headers: authHeaders });
      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: "Error" }));
        setBackupStatus(`Failed: ${err.detail}`);
        return;
      }
      const data = await res.json();
      setBackupStatus(`Saved: ${data.filename} (${data.size_mb} MB)`);
    } catch {
      setBackupStatus("Network error");
    } finally {
      setBackupLoading(false);
    }
  };

  const downloadLatest = async () => {
    try {
      const listRes = await fetch("/api/v1/backup/list", { headers: authHeaders });
      if (!listRes.ok) { setBackupStatus("Cannot list backups"); return; }
      const { backups } = await listRes.json();
      if (!backups || backups.length === 0) { setBackupStatus("No backups found"); return; }
      const latest = backups[0].filename;
      const a = document.createElement("a");
      a.href = `/api/v1/backup/download/${latest}`;
      // Pass auth via a temporary anchor — works for same-origin only
      a.setAttribute("download", latest);
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
    } catch {
      setBackupStatus("Download failed");
    }
  };

  const handleRestoreFile = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    if (!file.name.endsWith(".sql.gz")) { setBackupStatus("Must be a .sql.gz file"); return; }
    if (!confirm(`Restore database from "${file.name}"? This will overwrite current data.`)) return;

    setBackupLoading(true);
    setBackupStatus("Restoring…");
    const form = new FormData();
    form.append("file", file);
    try {
      const res = await fetch("/api/v1/backup/restore", {
        method: "POST",
        headers: authHeaders,
        body: form,
      });
      const data = await res.json().catch(() => ({ detail: "Parse error" }));
      setBackupStatus(res.ok ? `Restored: ${data.message}` : `Failed: ${data.detail}`);
    } catch {
      setBackupStatus("Restore network error");
    } finally {
      setBackupLoading(false);
      e.target.value = "";
    }
  };

  const activeMode = MODES.find((m) => m.id === mode) ?? MODES[0];

  return (
    <aside
      className={clsx(
        "flex flex-col h-full border-r border-neutral-800 bg-neutral-950 transition-all duration-300 flex-shrink-0",
        collapsed ? "w-12" : "w-56",
      )}
    >
      {/* Header */}
      <div className="flex items-center justify-between px-3 py-3 border-b border-neutral-800">
        {!collapsed && (
          <span className="text-xs font-semibold text-neutral-400 uppercase tracking-wider">IRA</span>
        )}
        <button
          onClick={() => setCollapsed((c) => !c)}
          className="ml-auto text-neutral-600 hover:text-neutral-300 transition-colors"
          title={collapsed ? "Expand sidebar" : "Collapse sidebar"}
        >
          {collapsed ? <ChevronRight className="w-4 h-4" /> : <ChevronLeft className="w-4 h-4" />}
        </button>
      </div>

      {/* New Chat button */}
      <div className="px-2 pt-3 pb-2">
        <button
          onClick={onNewChat}
          className={clsx(
            "w-full flex items-center gap-2 rounded-xl border transition-all duration-200 text-sm font-medium",
            collapsed ? "justify-center p-2" : "px-3 py-2",
            "border-neutral-700 text-neutral-300 hover:border-neutral-500 hover:text-white hover:bg-neutral-800",
          )}
          title="New conversation"
        >
          <span className="text-base leading-none">+</span>
          {!collapsed && <span>New Chat</span>}
        </button>
      </div>

      {/* Mode selector */}
      <div className={clsx("px-2 pb-3 border-b border-neutral-800/50", collapsed ? "space-y-1" : "space-y-1")}>
        {!collapsed && (
          <p className="px-1 pt-1 pb-1 text-[10px] font-semibold text-neutral-600 uppercase tracking-wider">
            Mode
          </p>
        )}
        {MODES.map((m) => {
          const isActive = m.id === mode;
          return (
            <button
              key={m.id}
              onClick={() => onModeChange(m.id)}
              title={collapsed ? m.label : m.description}
              className={clsx(
                "w-full flex items-center gap-2.5 rounded-xl border transition-all duration-200",
                collapsed ? "justify-center p-2.5" : "px-3 py-2",
                isActive
                  ? `${m.accent} font-medium`
                  : "border-transparent text-neutral-500 hover:text-neutral-300 hover:bg-neutral-800/50",
              )}
            >
              {m.icon}
              {!collapsed && <span className="text-sm">{m.label}</span>}
            </button>
          );
        })}
      </div>

      {/* Recent conversations */}
      {!collapsed && (
        <div className="flex-1 overflow-y-auto px-2 pt-3 space-y-0.5">
          <p className="px-1 pb-1 text-[10px] font-semibold text-neutral-600 uppercase tracking-wider">
            Recent
          </p>
          {recentChats.length === 0 ? (
            <p className="px-2 py-3 text-xs text-neutral-700 italic">No conversations yet</p>
          ) : (
            recentChats.map((chat) => (
              <button
                key={chat.id}
                className="w-full text-left px-2 py-2 rounded-lg hover:bg-neutral-800 transition-colors group"
              >
                <p className="text-xs text-neutral-300 truncate">{chat.title}</p>
                <div className="flex items-center gap-1 mt-0.5">
                  <Clock className="w-2.5 h-2.5 text-neutral-700" />
                  <span className="text-[10px] text-neutral-700">
                    {formatRelative(chat.timestamp)}
                  </span>
                </div>
              </button>
            ))
          )}
        </div>
      )}

      {/* Backup & Restore section */}
      {!collapsed && token && (
        <div className="px-2 py-3 border-t border-neutral-800/50">
          <p className="px-1 pb-2 text-[10px] font-semibold text-neutral-600 uppercase tracking-wider flex items-center gap-1">
            <HardDrive className="w-2.5 h-2.5" />
            Backup & Restore
          </p>
          <input
            ref={restoreInputRef}
            type="file"
            accept=".sql.gz"
            className="hidden"
            onChange={handleRestoreFile}
          />
          <div className="space-y-1">
            <button
              onClick={triggerBackup}
              disabled={backupLoading}
              className="w-full flex items-center gap-2 px-2 py-1.5 rounded-lg text-xs text-neutral-400 hover:text-white hover:bg-neutral-800 transition-colors disabled:opacity-40"
            >
              {backupLoading ? <RefreshCw className="w-3 h-3 animate-spin" /> : <HardDrive className="w-3 h-3" />}
              Create Backup Now
            </button>
            <button
              onClick={downloadLatest}
              disabled={backupLoading}
              className="w-full flex items-center gap-2 px-2 py-1.5 rounded-lg text-xs text-neutral-400 hover:text-white hover:bg-neutral-800 transition-colors disabled:opacity-40"
            >
              <Download className="w-3 h-3" />
              Download Latest
            </button>
            <button
              onClick={() => restoreInputRef.current?.click()}
              disabled={backupLoading}
              className="w-full flex items-center gap-2 px-2 py-1.5 rounded-lg text-xs text-red-500 hover:text-red-400 hover:bg-red-500/10 transition-colors disabled:opacity-40"
            >
              <Upload className="w-3 h-3" />
              Restore from File
            </button>
            {backupStatus && (
              <p className="px-2 text-[10px] text-neutral-500 break-words leading-tight">{backupStatus}</p>
            )}
          </div>
        </div>
      )}

      {/* Bottom: current mode indicator */}
      {!collapsed && (
        <div className={clsx("px-3 py-3 border-t border-neutral-800 flex items-center gap-2", activeMode.accent)}>
          {activeMode.icon}
          <span className="text-xs font-medium">{activeMode.label} mode</span>
        </div>
      )}
    </aside>
  );
}
