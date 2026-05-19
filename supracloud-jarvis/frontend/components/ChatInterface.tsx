"use client";

import { useState, useRef, useEffect, useCallback } from "react";
import { Send, Loader2 } from "lucide-react";
import clsx from "clsx";

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
}

export default function ChatInterface({ sessionId, token }: Props) {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [isStreaming, setIsStreaming] = useState(false);
  const bottomRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  // Auto-resize textarea
  useEffect(() => {
    const el = textareaRef.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = Math.min(el.scrollHeight, 128) + "px";
  }, [input]);

  const sendMessage = useCallback(async () => {
    const text = input.trim();
    if (!text || isStreaming) return;

    const userMsgId = Date.now().toString();
    const assistantMsgId = (Date.now() + 1).toString();

    setMessages((prev) => [
      ...prev,
      { id: userMsgId, role: "user", content: text },
      { id: assistantMsgId, role: "assistant", content: "", isStreaming: true },
    ]);
    setInput("");
    setIsStreaming(true);

    try {
      const res = await fetch("/api/v1/chat/stream", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify({ message: text, session_id: sessionId, stream: true }),
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
                    ? {
                        ...m,
                        isStreaming: false,
                        agent: data.agent,
                        latencyMs: data.latency_ms,
                      }
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
    } catch (err) {
      setMessages((prev) =>
        prev.map((m) =>
          m.id === assistantMsgId
            ? {
                ...m,
                content: "Connection error. Please check your network and try again.",
                isStreaming: false,
              }
            : m
        )
      );
    } finally {
      setIsStreaming(false);
      textareaRef.current?.focus();
    }
  }, [input, isStreaming, sessionId, token]);

  const onKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      sendMessage();
    }
  };

  const AGENT_LABELS: Record<string, string> = {
    conversational: "IRA",
    researcher:     "Researcher",
    security:       "Security Guardian",
    website:        "Business Manager",
    creator:        "Agent Creator",
    executor:       "Executor",
  };

  return (
    <div className="flex flex-col h-full">
      {/* Message list */}
      <div className="flex-1 overflow-y-auto px-4 py-6 space-y-5">
        {messages.length === 0 && (
          <div className="flex flex-col items-center justify-center h-full text-center select-none">
            <div className="w-20 h-20 rounded-full bg-saffron-500/10 border border-saffron-500/20 flex items-center justify-center mb-5">
              <span className="text-4xl">✦</span>
            </div>
            <h2 className="text-xl font-semibold text-white mb-2">
              Hello, I am IRA
            </h2>
            <p className="text-neutral-500 text-sm max-w-xs leading-relaxed">
              Your Intelligent Responsive Assistant. Ask me anything — I can
              research, monitor security, manage tasks, and more.
            </p>
          </div>
        )}

        {messages.map((msg) => (
          <div
            key={msg.id}
            className={clsx("flex", msg.role === "user" ? "justify-end" : "justify-start")}
          >
            {msg.role === "assistant" && (
              <div className="w-6 h-6 rounded-full bg-saffron-500/20 border border-saffron-500/30 flex items-center justify-center flex-shrink-0 mt-1 mr-2 select-none">
                <span className="text-xs">✦</span>
              </div>
            )}
            <div className="max-w-[78%]">
              <div
                className={clsx(
                  "rounded-2xl px-4 py-3 text-sm leading-relaxed break-words",
                  msg.role === "user"
                    ? "bg-saffron-500 text-white rounded-br-sm"
                    : "bg-neutral-800 text-neutral-100 rounded-bl-sm border border-neutral-700/60"
                )}
              >
                <p className="whitespace-pre-wrap">{msg.content}</p>
                {msg.isStreaming && (
                  <span className="inline-block w-1.5 h-4 bg-saffron-400 cursor-blink ml-0.5 align-middle" />
                )}
              </div>
              {msg.agent && !msg.isStreaming && (
                <p className="text-xs text-neutral-600 mt-1 pl-1">
                  {AGENT_LABELS[msg.agent] ?? msg.agent}
                  {msg.latencyMs ? ` · ${msg.latencyMs}ms` : ""}
                </p>
              )}
            </div>
          </div>
        ))}
        <div ref={bottomRef} />
      </div>

      {/* Input bar */}
      <div className="border-t border-neutral-800 px-4 py-3 flex-shrink-0">
        <div className="flex items-end gap-2 bg-neutral-900 rounded-2xl border border-neutral-700 px-4 py-2 focus-within:border-saffron-500/40 transition-colors">
          <textarea
            ref={textareaRef}
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={onKeyDown}
            placeholder="Ask IRA anything…"
            rows={1}
            className="flex-1 bg-transparent text-sm text-white placeholder-neutral-600 resize-none outline-none py-1 leading-relaxed"
          />
          <button
            onClick={sendMessage}
            disabled={!input.trim() || isStreaming}
            className={clsx(
              "flex-shrink-0 w-8 h-8 rounded-xl flex items-center justify-center transition-all mb-0.5",
              input.trim() && !isStreaming
                ? "bg-saffron-500 hover:bg-saffron-600 text-white shadow-md"
                : "bg-neutral-800 text-neutral-600 cursor-not-allowed"
            )}
          >
            {isStreaming ? (
              <Loader2 className="w-4 h-4 animate-spin" />
            ) : (
              <Send className="w-4 h-4" />
            )}
          </button>
        </div>
        <p className="text-xs text-neutral-700 text-center mt-1.5">
          Enter to send · Shift+Enter for new line
        </p>
      </div>
    </div>
  );
}
