"use client";

import { useState, useRef, useEffect, useCallback } from "react";
import { Send, Square, Copy, Check, Loader2 } from "lucide-react";
import clsx from "clsx";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

import type { AppMode } from "./Sidebar";

interface Message {
  id: string;
  role: "user" | "assistant";
  content: string;
  agent?: string;
  latencyMs?: number;
  isStreaming?: boolean;
}

interface Props {
  sessionId: string;
  token: string;
  mode?: AppMode;
}

const URL_RE = /https?:\/\/\S+/;

const AGENT_LABELS: Record<string, string> = {
  conversational: "IRA",
  researcher:     "Researcher",
  security:       "Security Guardian",
  website:        "Business Manager",
  creator:        "Agent Creator",
  executor:       "Executor",
  career:         "Career Engine",
  tutor:          "Supracloud Tutor",
  digital:        "Digital Brain",
  security_gate:  "Security Gate",
};

// Suggestion chips per mode
const SUGGESTIONS: Record<AppMode, string[]> = {
  assistant: [
    "What can you do?",
    "Analyze my GitHub repos",
    "Scan for security threats",
    "Open VS Code",
  ],
  tutor: [
    "I'm learning Docker",
    "Explain async/await",
    "Review my Python code",
    "Teach me LangGraph",
  ],
  bodyguard: [
    "Scan for threats",
    "Check SSH logs",
    "Lock down the system",
    "Show security events",
  ],
};

function CopyButton({ text }: { text: string }) {
  const [copied, setCopied] = useState(false);

  const copy = async () => {
    await navigator.clipboard.writeText(text);
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  };

  return (
    <button
      onClick={copy}
      className="opacity-0 group-hover:opacity-100 transition-opacity p-1 rounded text-neutral-600 hover:text-neutral-300"
      title="Copy"
    >
      {copied ? <Check className="w-3 h-3 text-green-400" /> : <Copy className="w-3 h-3" />}
    </button>
  );
}

export default function ChatInterface({ sessionId, token, mode = "assistant" }: Props) {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [isStreaming, setIsStreaming] = useState(false);
  const [streamingId, setStreamingId] = useState<string | null>(null);
  const bottomRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const abortRef = useRef<AbortController | null>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  // Auto-resize textarea
  useEffect(() => {
    const el = textareaRef.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = Math.min(el.scrollHeight, 140) + "px";
  }, [input]);

  const stopStreaming = useCallback(() => {
    abortRef.current?.abort();
    abortRef.current = null;
    setIsStreaming(false);
    setStreamingId(null);
    // Mark current streaming message as done
    setMessages((prev) =>
      prev.map((m) => (m.isStreaming ? { ...m, isStreaming: false } : m))
    );
  }, []);

  const sendMessage = useCallback(
    async (text?: string) => {
      const content = (text ?? input).trim();
      if (!content || isStreaming) return;

      const userMsgId = Date.now().toString();
      const assistantMsgId = (Date.now() + 1).toString();

      setMessages((prev) => [
        ...prev,
        { id: userMsgId, role: "user", content },
        { id: assistantMsgId, role: "assistant", content: "", isStreaming: true },
      ]);
      setInput("");
      setIsStreaming(true);
      setStreamingId(assistantMsgId);

      const controller = new AbortController();
      abortRef.current = controller;

      try {
        const res = await fetch("/api/v1/chat/stream", {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            Authorization: `Bearer ${token}`,
          },
          body: JSON.stringify({
            message: content,
            session_id: sessionId,
            stream: true,
            mode: mode === "bodyguard" ? "assistant" : mode,
          }),
          signal: controller.signal,
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
                setMessages((prev) =>
                  prev.map((m) =>
                    m.id === assistantMsgId
                      ? { ...m, content: m.content + data.token }
                      : m
                  )
                );
              } else if (data.done) {
                setMessages((prev) =>
                  prev.map((m) =>
                    m.id === assistantMsgId
                      ? { ...m, isStreaming: false, agent: data.agent, latencyMs: data.latency_ms }
                      : m
                  )
                );
              } else if (data.error) {
                setMessages((prev) =>
                  prev.map((m) =>
                    m.id === assistantMsgId
                      ? { ...m, content: `⚠ ${data.error}`, isStreaming: false }
                      : m
                  )
                );
              }
            } catch {
              // ignore malformed SSE frames
            }
          }
        }
      } catch (err: any) {
        if (err.name !== "AbortError") {
          setMessages((prev) =>
            prev.map((m) =>
              m.id === assistantMsgId
                ? {
                    ...m,
                    content: "Connection error — check your network and try again.",
                    isStreaming: false,
                  }
                : m
            )
          );
        }
      } finally {
        setIsStreaming(false);
        setStreamingId(null);
        abortRef.current = null;
        textareaRef.current?.focus();
      }
    },
    [input, isStreaming, sessionId, token, mode]
  );

  const onKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      sendMessage();
    }
  };

  const isTutor = mode === "tutor";
  const isBodyguard = mode === "bodyguard";
  const hasUrl = URL_RE.test(input);

  const accentSend = isTutor
    ? "bg-indigo-500 hover:bg-indigo-600 text-white"
    : isBodyguard
    ? "bg-red-500 hover:bg-red-600 text-white"
    : "bg-saffron-500 hover:bg-saffron-600 text-white";

  const accentBorder = isTutor
    ? "focus-within:border-indigo-500/50"
    : isBodyguard
    ? "focus-within:border-red-500/50"
    : "focus-within:border-saffron-500/40";

  const suggestions = SUGGESTIONS[mode] ?? SUGGESTIONS.assistant;

  return (
    <div className="flex flex-col h-full">
      {/* Message list */}
      <div className="flex-1 overflow-y-auto px-4 py-6">
        {messages.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-full text-center select-none">
            <div
              className={clsx(
                "w-20 h-20 rounded-full flex items-center justify-center mb-5 border",
                isTutor
                  ? "bg-indigo-500/10 border-indigo-500/20"
                  : isBodyguard
                  ? "bg-red-500/10 border-red-500/20"
                  : "bg-saffron-500/10 border-saffron-500/20"
              )}
            >
              <span className="text-4xl">
                {isTutor ? "🎓" : isBodyguard ? "🛡" : "✦"}
              </span>
            </div>
            <h2 className="text-xl font-semibold text-white mb-1">
              {isTutor
                ? "Supracloud Tutor"
                : isBodyguard
                ? "IRA Bodyguard Mode"
                : "Hello, I am IRA"}
            </h2>
            <p className="text-neutral-500 text-sm max-w-xs leading-relaxed mb-6">
              {isTutor
                ? "I won't give you the answer — I'll help you find it. What are you learning today?"
                : isBodyguard
                ? "Active security monitoring. Ask me to scan threats, check logs, or lock down."
                : "Your Intelligent Responsive Assistant. Paste a URL, ask anything, or use the mic."}
            </p>
            {/* Suggestion chips */}
            <div className="flex flex-wrap justify-center gap-2 max-w-sm">
              {suggestions.map((s) => (
                <button
                  key={s}
                  onClick={() => sendMessage(s)}
                  className={clsx(
                    "px-3 py-1.5 rounded-full text-xs border transition-all duration-150",
                    isTutor
                      ? "border-indigo-500/30 text-indigo-400 hover:bg-indigo-500/10"
                      : isBodyguard
                      ? "border-red-500/30 text-red-400 hover:bg-red-500/10"
                      : "border-saffron-500/30 text-saffron-400 hover:bg-saffron-500/10"
                  )}
                >
                  {s}
                </button>
              ))}
            </div>
          </div>
        ) : (
          <div className="space-y-5 max-w-3xl mx-auto">
            {messages.map((msg) => (
              <div
                key={msg.id}
                className={clsx(
                  "flex animate-fade-in",
                  msg.role === "user" ? "justify-end" : "justify-start"
                )}
              >
                {msg.role === "assistant" && (
                  <div className="w-6 h-6 rounded-full bg-saffron-500/20 border border-saffron-500/30 flex items-center justify-center flex-shrink-0 mt-1 mr-2 select-none">
                    <span className="text-xs">✦</span>
                  </div>
                )}
                <div className="max-w-[78%] group">
                  <div
                    className={clsx(
                      "rounded-2xl px-4 py-3 text-sm leading-relaxed break-words",
                      msg.role === "user"
                        ? "bg-saffron-500 text-white rounded-br-sm"
                        : "bg-neutral-800/80 text-neutral-100 rounded-bl-sm border border-neutral-700/60"
                    )}
                  >
                    {msg.role === "assistant" ? (
                      <div className="prose prose-invert prose-sm max-w-none prose-p:leading-relaxed prose-p:my-1 prose-headings:text-white prose-headings:font-semibold prose-code:text-saffron-300 prose-code:bg-neutral-900 prose-code:px-1 prose-code:rounded prose-pre:bg-neutral-900 prose-pre:border prose-pre:border-neutral-700">
                        {msg.content && <ReactMarkdown remarkPlugins={[remarkGfm]}>{msg.content}</ReactMarkdown>}
                        {msg.isStreaming && (
                          <span className="inline-block w-1.5 h-4 bg-saffron-400 ml-0.5 align-middle animate-cursor-blink" />
                        )}
                      </div>
                    ) : (
                      <p className="whitespace-pre-wrap">{msg.content}</p>
                    )}
                  </div>
                  <div className="flex items-center gap-1 mt-1 pl-1">
                    {msg.agent && !msg.isStreaming && (
                      <p className="text-[11px] text-neutral-600">
                        {AGENT_LABELS[msg.agent] ?? msg.agent}
                        {msg.latencyMs ? ` · ${msg.latencyMs}ms` : ""}
                      </p>
                    )}
                    {msg.role === "assistant" && !msg.isStreaming && msg.content && (
                      <CopyButton text={msg.content} />
                    )}
                  </div>
                </div>
              </div>
            ))}
            <div ref={bottomRef} />
          </div>
        )}
        {messages.length > 0 && <div ref={bottomRef} />}
      </div>

      {/* Input bar */}
      <div className="border-t border-neutral-800 px-4 py-3 flex-shrink-0">
        <div className="max-w-3xl mx-auto">
          {hasUrl && (
            <div className="mb-2 px-3 py-1.5 rounded-lg bg-indigo-500/10 border border-indigo-500/20 text-indigo-300 text-xs flex items-center gap-1.5">
              <span>🔗</span>
              <span>IRA will browse and summarize this link for you.</span>
            </div>
          )}
          <div
            className={clsx(
              "flex items-end gap-2 bg-neutral-900/80 rounded-2xl border border-neutral-700 px-4 py-2 transition-colors",
              accentBorder
            )}
          >
            <textarea
              ref={textareaRef}
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={onKeyDown}
              placeholder={
                isTutor
                  ? "Submit your code or question…"
                  : isBodyguard
                  ? "Ask IRA to scan threats, check logs, or lock down…"
                  : "Ask IRA anything, or paste a URL…"
              }
              rows={1}
              className="flex-1 bg-transparent text-sm text-white placeholder-neutral-600 resize-none outline-none py-1 leading-relaxed"
            />
            {isStreaming ? (
              <button
                onClick={stopStreaming}
                className="flex-shrink-0 w-8 h-8 rounded-xl flex items-center justify-center bg-red-500/20 border border-red-500/50 text-red-400 hover:bg-red-500/30 transition-all mb-0.5"
                title="Stop"
              >
                <Square className="w-3.5 h-3.5" />
              </button>
            ) : (
              <button
                onClick={() => sendMessage()}
                disabled={!input.trim()}
                className={clsx(
                  "flex-shrink-0 w-8 h-8 rounded-xl flex items-center justify-center transition-all mb-0.5",
                  input.trim()
                    ? `${accentSend} shadow-md`
                    : "bg-neutral-800 text-neutral-600 cursor-not-allowed"
                )}
              >
                <Send className="w-4 h-4" />
              </button>
            )}
          </div>
          <p className="text-[11px] text-neutral-700 text-center mt-1.5">
            Enter to send · Shift+Enter for new line
            {isTutor && " · Tutor mode — Socratic method enabled"}
            {isBodyguard && " · Bodyguard mode — security commands active"}
          </p>
        </div>
      </div>
    </div>
  );
}
