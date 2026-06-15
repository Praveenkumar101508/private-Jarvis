"use client";

import { useState, useRef, useEffect, useCallback } from "react";
import { ArrowUp, Square, RotateCcw } from "lucide-react";
import clsx from "clsx";

interface Message {
  id: string;
  role: "user" | "assistant";
  content: string;
  agent?: string;
  latencyMs?: number;
  isStreaming?: boolean;
}

function renderContent(text: string) {
  // Minimal markdown: **bold**, `code`, ```blocks```, newlines
  const lines = text.split("\n");
  const elements: React.ReactNode[] = [];
  let i = 0;

  while (i < lines.length) {
    const line = lines[i];

    // Code block
    if (line.startsWith("```")) {
      const blockLines: string[] = [];
      i++;
      while (i < lines.length && !lines[i].startsWith("```")) {
        blockLines.push(lines[i]);
        i++;
      }
      elements.push(
        <pre key={i} className="bg-black/40 border border-white/[0.07] rounded-lg p-3 my-2 overflow-x-auto">
          <code className="text-[13px] text-green-300 font-mono leading-relaxed">
            {blockLines.join("\n")}
          </code>
        </pre>
      );
      i++;
      continue;
    }

    // Regular line — inline bold + code
    const parts = line.split(/(\*\*[^*]+\*\*|`[^`]+`)/g);
    const rendered = parts.map((p, j) => {
      if (p.startsWith("**") && p.endsWith("**")) return <strong key={j} className="text-white font-semibold">{p.slice(2, -2)}</strong>;
      if (p.startsWith("`") && p.endsWith("`")) return <code key={j} className="bg-white/8 px-1.5 py-0.5 rounded text-[0.82em] text-amber-300 font-mono">{p.slice(1, -1)}</code>;
      return p;
    });

    if (line.trim()) {
      elements.push(<p key={i} className="leading-relaxed">{rendered}</p>);
    } else if (i > 0) {
      elements.push(<div key={i} className="h-2" />);
    }
    i++;
  }
  return <div className="prose-ira space-y-0.5 text-[15px]">{elements}</div>;
}

const AGENT_LABELS: Record<string, string> = {
  conversational: "IRA",
  researcher:     "Research",
  security:       "Security",
  website:        "Business",
  creator:        "Creator",
  executor:       "Executor",
};

const SUGGESTIONS = [
  "What can you help me with?",
  "Summarise my latest tasks",
  "Check my security alerts",
  "Schedule a briefing for tomorrow",
];

interface Props { sessionId: string; token: string; }

export default function ChatInterface({ sessionId, token }: Props) {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [isStreaming, setIsStreaming] = useState(false);
  const bottomRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const abortRef = useRef<AbortController | null>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  useEffect(() => {
    const el = textareaRef.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = Math.min(el.scrollHeight, 160) + "px";
  }, [input]);

  const stop = useCallback(() => {
    abortRef.current?.abort();
    setIsStreaming(false);
  }, []);

  const sendMessage = useCallback(async (text?: string) => {
    const msg = (text ?? input).trim();
    if (!msg || isStreaming) return;

    const userMsgId = crypto.randomUUID();
    const asstMsgId = crypto.randomUUID();

    setMessages(prev => [
      ...prev,
      { id: userMsgId, role: "user", content: msg },
      { id: asstMsgId, role: "assistant", content: "", isStreaming: true },
    ]);
    setInput("");
    setIsStreaming(true);

    const ctrl = new AbortController();
    abortRef.current = ctrl;

    try {
      const res = await fetch("/api/v1/chat/stream", {
        method: "POST",
        headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
        body: JSON.stringify({ message: msg, session_id: sessionId, stream: true }),
        signal: ctrl.signal,
      });

      if (!res.ok || !res.body) throw new Error(`HTTP ${res.status}`);

      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buf = "";

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buf += decoder.decode(value, { stream: true });
        const lines = buf.split("\n");
        buf = lines.pop() ?? "";

        for (const line of lines) {
          if (!line.startsWith("data:")) continue;
          const raw = line.slice(5).trim();
          if (!raw) continue;
          try {
            const data = JSON.parse(raw);
            if (data.token !== undefined) {
              setMessages(prev => prev.map(m =>
                m.id === asstMsgId ? { ...m, content: m.content + data.token } : m
              ));
            } else if (data.done) {
              setMessages(prev => prev.map(m =>
                m.id === asstMsgId ? { ...m, isStreaming: false, agent: data.agent, latencyMs: data.latency_ms } : m
              ));
            } else if (data.error) {
              setMessages(prev => prev.map(m =>
                m.id === asstMsgId ? { ...m, content: data.error, isStreaming: false } : m
              ));
            }
          } catch { /* ignore malformed frames */ }
        }
      }
    } catch (err: any) {
      if (err?.name !== "AbortError") {
        setMessages(prev => prev.map(m =>
          m.id === asstMsgId ? { ...m, content: "Connection error. Is IRA running?", isStreaming: false } : m
        ));
      } else {
        setMessages(prev => prev.map(m =>
          m.id === asstMsgId ? { ...m, isStreaming: false } : m
        ));
      }
    } finally {
      setIsStreaming(false);
      textareaRef.current?.focus();
    }
  }, [input, isStreaming, sessionId, token]);

  const clearChat = () => setMessages([]);

  const onKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); sendMessage(); }
  };

  return (
    <div className="flex flex-col h-full max-w-3xl mx-auto w-full">
      {/* Messages */}
      <div className="flex-1 overflow-y-auto px-4 py-6">
        {messages.length === 0 ? (
          /* Empty state — centred, clean */
          <div className="flex flex-col items-center justify-center h-full gap-6 select-none">
            <div className="text-center">
              <div className="w-14 h-14 rounded-2xl bg-gradient-to-br from-orange-500/20 to-purple-500/10 border border-white/[0.08] flex items-center justify-center mx-auto mb-4 shadow-lg">
                <span className="text-2xl">✦</span>
              </div>
              <h2 className="text-xl font-semibold text-white/90 tracking-tight">How can I help?</h2>
              <p className="text-white/30 text-sm mt-1">IRA · SupraCloud Private AI</p>
            </div>

            {/* Suggestion chips */}
            <div className="flex flex-wrap gap-2 justify-center max-w-sm">
              {SUGGESTIONS.map(s => (
                <button
                  key={s}
                  onClick={() => sendMessage(s)}
                  className="text-xs text-white/50 border border-white/[0.08] hover:border-white/20 hover:text-white/80 px-3 py-1.5 rounded-full transition-all duration-150 bg-white/[0.02] hover:bg-white/[0.05]"
                >
                  {s}
                </button>
              ))}
            </div>
          </div>
        ) : (
          <div className="space-y-6">
            {messages.map(msg => (
              <div key={msg.id} className={clsx("msg-enter flex gap-3", msg.role === "user" ? "justify-end" : "justify-start")}>
                {msg.role === "assistant" && (
                  <div className="w-7 h-7 rounded-full bg-gradient-to-br from-orange-500/30 to-purple-500/20 border border-white/10 flex items-center justify-center flex-shrink-0 mt-0.5 shadow">
                    <span className="text-[11px]">✦</span>
                  </div>
                )}
                <div className={clsx("max-w-[85%]", msg.role === "user" ? "max-w-[75%]" : "")}>
                  <div className={clsx(
                    "rounded-2xl px-4 py-3 text-sm break-words",
                    msg.role === "user"
                      ? "bg-[#1e1e1e] text-white/90 rounded-br-sm border border-white/[0.07]"
                      : "text-white/85"
                  )}>
                    {msg.role === "assistant"
                      ? renderContent(msg.content)
                      : <p className="whitespace-pre-wrap leading-relaxed">{msg.content}</p>
                    }
                    {msg.isStreaming && (
                      <span className="inline-block w-[3px] h-[1.1em] bg-orange-400/80 cursor-blink ml-0.5 align-[-2px] rounded-sm" />
                    )}
                  </div>
                  {msg.agent && !msg.isStreaming && msg.role === "assistant" && (
                    <p className="text-[11px] text-white/20 mt-1.5 pl-1">
                      {AGENT_LABELS[msg.agent] ?? msg.agent}
                      {msg.latencyMs ? ` · ${msg.latencyMs}ms` : ""}
                    </p>
                  )}
                </div>
              </div>
            ))}
            <div ref={bottomRef} />
          </div>
        )}
      </div>

      {/* Input — ChatGPT style bottom bar */}
      <div className="px-4 pb-5 flex-shrink-0">
        {messages.length > 0 && (
          <div className="flex justify-center mb-2">
            <button
              onClick={clearChat}
              className="flex items-center gap-1 text-[11px] text-white/20 hover:text-white/40 transition-colors"
            >
              <RotateCcw className="w-3 h-3" />
              New conversation
            </button>
          </div>
        )}

        <div className="relative bg-[#1a1a1a] border border-white/[0.08] rounded-2xl focus-within:border-white/[0.15] transition-colors shadow-xl">
          <textarea
            ref={textareaRef}
            value={input}
            onChange={e => setInput(e.target.value)}
            onKeyDown={onKeyDown}
            placeholder="Message IRA…"
            rows={1}
            className="w-full bg-transparent text-sm text-white/90 placeholder-white/20 resize-none outline-none px-4 pt-3.5 pb-12 leading-relaxed"
          />
          {/* Bottom row of input */}
          <div className="absolute bottom-3 right-3 flex items-center gap-2">
            <span className="text-[11px] text-white/15 hidden sm:block">⏎ send</span>
            <button
              onClick={isStreaming ? stop : sendMessage}
              disabled={!isStreaming && !input.trim()}
              className={clsx(
                "w-8 h-8 rounded-xl flex items-center justify-center transition-all",
                isStreaming
                  ? "bg-white/10 hover:bg-white/15 text-white/70"
                  : input.trim()
                    ? "bg-white text-black hover:bg-white/90 shadow-md"
                    : "bg-white/5 text-white/15 cursor-not-allowed"
              )}
            >
              {isStreaming
                ? <Square className="w-3.5 h-3.5 fill-current" />
                : <ArrowUp className="w-4 h-4" />
              }
            </button>
          </div>
        </div>
        <p className="text-[11px] text-white/12 text-center mt-2">
          IRA is private · runs locally · no data leaves your server
        </p>
      </div>
    </div>
  );
}
