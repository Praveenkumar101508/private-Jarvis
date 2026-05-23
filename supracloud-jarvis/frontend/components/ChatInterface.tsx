"use client";

import { useState, useRef, useEffect, useCallback } from "react";
import { Send, Square, Copy, Check, Loader2, Zap, ChevronDown, ChevronUp, Paperclip, X, AlertCircle, DollarSign, Brain, Code2 } from "lucide-react";
import clsx from "clsx";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

import type { AppMode } from "./Sidebar";

interface AgentBubble {
  name: string;
  label: string;
  emoji: string;
  content: string;
  done: boolean;
}

interface AttachedFile {
  name: string;
  dataUrl: string;
  base64: string;
  mimeType: string;
}

interface Message {
  id: string;
  role: "user" | "assistant";
  content: string;
  agent?: string;
  latencyMs?: number;
  isStreaming?: boolean;
  isExpert?: boolean;
  expertAgents?: AgentBubble[];
  expertPanelOpen?: boolean;
  imageDataUrl?: string;
  generatedImageB64?: string;
  generatedImagePrompt?: string;
  usedLiveX?: boolean;
  isEngineer?: boolean;
}

interface Props {
  sessionId: string;
  token: string;
  mode?: AppMode;
}

const URL_RE = /https?:\/\/\S+/;
const IMAGE_GEN_RE = /\b(generate\s+(an?\s+)?image|create\s+(an?\s+)?(image|picture|photo|art|drawing)|draw\s+(me\s+)?|make\s+(an?\s+)?(image|picture)|imagine\s+(an?\s+)?|visualize|render\s+|design\s+(an?\s+)?(image|logo|banner))\b/i;
const IMAGE_EDIT_RE = /\b(edit\s+(this\s+)?image|modify\s+(this\s+)?image|change\s+(this\s+)?image|make\s+(it|this)\s+(look|appear)|add\s+to\s+(this|the)\s+image|remove\s+from|transform\s+(this\s+)?image|enhance|upscale|colorize|restore)\b/i;

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
  vision:         "Vision Analysis",
  expert_mode:    "Expert Mode",
  image_gen:      "Image Generation",
  image_edit:     "Image Editing",
  engineer:       "Engineer Mode",
};

function estimateExpertTokens(text: string): number {
  // 5 agents each see the full context; rough 4 chars/token + fixed overhead
  return Math.ceil((text.length / 4) * 5 + 2000);
}

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
  const [expertMode, setExpertMode] = useState(false);
  const [grokMode, setGrokMode] = useState(false);
  const [engineerMode, setEngineerMode] = useState(false);
  const [costGuard, setCostGuard] = useState(true);
  const [attachedFile, setAttachedFile] = useState<AttachedFile | null>(null);
  const [showCostConfirm, setShowCostConfirm] = useState(false);
  const [pendingQuery, setPendingQuery] = useState("");
  const [estimatedTokens, setEstimatedTokens] = useState(0);
  const bottomRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const abortRef = useRef<AbortController | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

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

  const toggleExpertPanel = useCallback((msgId: string) => {
    setMessages((prev) =>
      prev.map((m) => m.id === msgId ? { ...m, expertPanelOpen: !m.expertPanelOpen } : m)
    );
  }, []);

  const handleFileAttach = useCallback((e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = (ev) => {
      const dataUrl = ev.target?.result as string;
      const base64 = dataUrl.split(",")[1] ?? "";
      setAttachedFile({ name: file.name, dataUrl, base64, mimeType: file.type || "image/jpeg" });
    };
    reader.readAsDataURL(file);
    e.target.value = "";  // allow re-selecting same file
  }, []);

  const sendVisionMessage = useCallback(
    async (content: string, file: AttachedFile) => {
      const userMsgId = Date.now().toString();
      const assistantMsgId = (Date.now() + 1).toString();

      setMessages((prev) => [
        ...prev,
        { id: userMsgId, role: "user", content, imageDataUrl: file.dataUrl },
        { id: assistantMsgId, role: "assistant", content: "", isStreaming: true },
      ]);
      setInput("");
      setIsStreaming(true);
      setStreamingId(assistantMsgId);

      const controller = new AbortController();
      abortRef.current = controller;

      try {
        const res = await fetch("/api/v1/chat/vision", {
          method: "POST",
          headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
          body: JSON.stringify({
            message: content,
            session_id: sessionId,
            image_b64: file.base64,
            mime_type: file.mimeType,
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
                    m.id === assistantMsgId ? { ...m, content: m.content + data.token } : m
                  )
                );
              } else if (data.done) {
                setMessages((prev) =>
                  prev.map((m) =>
                    m.id === assistantMsgId
                      ? { ...m, isStreaming: false, agent: "vision", latencyMs: data.latency_ms }
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
            } catch { /* ignore malformed frames */ }
          }
        }
      } catch (err: any) {
        if (err.name !== "AbortError") {
          setMessages((prev) =>
            prev.map((m) =>
              m.id === assistantMsgId
                ? { ...m, content: "Vision error — please try again.", isStreaming: false }
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
    [sessionId, token]
  );

  const sendExpertMessage = useCallback(
    async (content: string, imageb64?: string, imageMime = "image/jpeg") => {
      const userMsgId = Date.now().toString();
      const assistantMsgId = (Date.now() + 1).toString();

      const initialAgents: AgentBubble[] = [
        { name: "researcher", label: "Researcher", emoji: "🔬", content: "", done: false },
        { name: "critic",     label: "Critic",     emoji: "🛡️", content: "", done: false },
        { name: "executor",   label: "Executor",   emoji: "⚙️", content: "", done: false },
        { name: "creator",    label: "Creator",    emoji: "✨", content: "", done: false },
        { name: "supervisor", label: "Supervisor", emoji: "🧠", content: "", done: false },
      ];

      setMessages((prev) => [
        ...prev,
        { id: userMsgId, role: "user", content },
        {
          id: assistantMsgId, role: "assistant", content: "",
          isStreaming: true, isExpert: true,
          expertAgents: initialAgents, expertPanelOpen: true,
        },
      ]);
      setInput("");
      setIsStreaming(true);
      setStreamingId(assistantMsgId);

      const controller = new AbortController();
      abortRef.current = controller;

      try {
        const res = await fetch("/api/v1/chat/expert", {
          method: "POST",
          headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
          body: JSON.stringify({
            message: content,
            session_id: sessionId,
            stream: true,
            ...(imageb64 ? { image_b64: imageb64, mime_type: imageMime } : {}),
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
              const agentName = data.agent;
              const chunk = data.chunk ?? "";
              const agentDone = data.done === true || data.agent_done === true;

              setMessages((prev) =>
                prev.map((m) => {
                  if (m.id !== assistantMsgId) return m;
                  const agents = (m.expertAgents ?? []).map((a) =>
                    a.name === agentName
                      ? { ...a, content: a.content + chunk, done: agentDone }
                      : a
                  );
                  // Build supervisor content as main message content
                  const supAgent = agents.find((a) => a.name === "supervisor");
                  const mainContent = supAgent?.content ?? m.content;
                  const allDone = agentDone && agentName === "supervisor";
                  return {
                    ...m,
                    content: mainContent,
                    expertAgents: agents,
                    isStreaming: !allDone,
                    agent: allDone ? "expert_mode" : m.agent,
                    latencyMs: allDone ? data.latency_ms : m.latencyMs,
                    usedLiveX: allDone ? data.used_live_x === true : m.usedLiveX,
                  };
                })
              );
            } catch { /* ignore malformed frames */ }
          }
        }
      } catch (err: any) {
        if (err.name !== "AbortError") {
          setMessages((prev) =>
            prev.map((m) =>
              m.id === assistantMsgId
                ? { ...m, content: "Expert Mode error — please try again.", isStreaming: false }
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
    [input, isStreaming, sessionId, token]
  );

  const sendMessage = useCallback(
    async (text?: string) => {
      const content = (text ?? input).trim();
      if (!content || isStreaming) return;

      if (expertMode) {
        // Cost Guard: warn before large queries (>50k estimated tokens across 5 agents)
        const estimated = estimateExpertTokens(content + (attachedFile ? " [image]" : ""));
        if (costGuard && estimated > 50_000) {
          setEstimatedTokens(estimated);
          setPendingQuery(content);
          setShowCostConfirm(true);
          return;
        }
        await sendExpertMessage(content, attachedFile?.base64, attachedFile?.mimeType);
        setAttachedFile(null);
        return;
      }

      // Image edit path: image attached + edit instruction
      if (attachedFile && IMAGE_EDIT_RE.test(content)) {
        // Route to vision endpoint which backend detects as image edit
        await sendVisionMessage(content, attachedFile);
        setAttachedFile(null);
        return;
      }

      // Vision path: image attached in normal mode (analysis, not editing)
      if (attachedFile) {
        await sendVisionMessage(content, attachedFile);
        setAttachedFile(null);
        return;
      }

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
            grok_mode: grokMode,
            engineer_mode: engineerMode,
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
              if (data.image_generated) {
                // Image generation result — store base64 on the message
                setMessages((prev) =>
                  prev.map((m) =>
                    m.id === assistantMsgId
                      ? {
                          ...m,
                          generatedImageB64: data.image_b64,
                          generatedImagePrompt: data.prompt,
                        }
                      : m
                  )
                );
              } else if (data.token !== undefined) {
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
                          usedLiveX: data.used_live_x === true,
                          isEngineer: data.is_engineer === true,
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
    [input, isStreaming, sessionId, token, mode, expertMode, grokMode, engineerMode, costGuard, attachedFile, sendExpertMessage, sendVisionMessage]
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
      {/* Cost Guard confirmation modal */}
      {showCostConfirm && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm">
          <div className="bg-neutral-900 border border-violet-500/30 rounded-2xl p-6 max-w-sm mx-4 shadow-2xl">
            <div className="flex items-center gap-2 mb-3">
              <AlertCircle className="w-5 h-5 text-amber-400" />
              <h3 className="text-white font-semibold">Cost Guard</h3>
            </div>
            <p className="text-neutral-300 text-sm mb-4">
              This Expert Mode query will use approximately{" "}
              <span className="text-amber-400 font-medium">
                {estimatedTokens.toLocaleString()} tokens
              </span>{" "}
              across all 5 agents. Continue?
            </p>
            <div className="flex gap-2">
              <button
                onClick={() => {
                  setShowCostConfirm(false);
                  sendExpertMessage(pendingQuery, attachedFile?.base64, attachedFile?.mimeType);
                  setAttachedFile(null);
                  setPendingQuery("");
                }}
                className="flex-1 py-2 rounded-xl bg-violet-600 hover:bg-violet-700 text-white text-sm font-medium transition-colors"
              >
                Proceed
              </button>
              <button
                onClick={() => { setShowCostConfirm(false); setPendingQuery(""); }}
                className="flex-1 py-2 rounded-xl bg-neutral-800 hover:bg-neutral-700 text-neutral-300 text-sm transition-colors"
              >
                Cancel
              </button>
            </div>
          </div>
        </div>
      )}
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
                        {/* Generated image display */}
                        {msg.generatedImageB64 && (
                          <div className="mb-3">
                            <img
                              src={`data:image/png;base64,${msg.generatedImageB64}`}
                              alt={msg.generatedImagePrompt ?? "Generated image"}
                              className="max-w-full rounded-xl border border-neutral-700 shadow-lg"
                            />
                            <a
                              href={`data:image/png;base64,${msg.generatedImageB64}`}
                              download="ira-generated.png"
                              className="mt-1 inline-block text-[10px] text-violet-400 hover:text-violet-300 no-underline"
                            >
                              Download image
                            </a>
                          </div>
                        )}
                        {msg.content && <ReactMarkdown remarkPlugins={[remarkGfm]}>{msg.content}</ReactMarkdown>}
                        {msg.isStreaming && (
                          <span className="inline-block w-1.5 h-4 bg-saffron-400 ml-0.5 align-middle animate-cursor-blink" />
                        )}
                      </div>
                    ) : (
                      <>
                        {msg.imageDataUrl && (
                          <img
                            src={msg.imageDataUrl}
                            alt="attachment"
                            className="mb-2 max-w-[240px] rounded-xl border border-neutral-600"
                          />
                        )}
                        <p className="whitespace-pre-wrap">{msg.content}</p>
                      </>
                    )}
                  </div>
                  {/* Agent Collaboration Panel (Expert Mode) */}
                  {msg.isExpert && msg.expertAgents && msg.expertAgents.length > 0 && (
                    <div className="mt-2 rounded-xl border border-violet-500/20 bg-violet-500/5 overflow-hidden">
                      <button
                        onClick={() => toggleExpertPanel(msg.id)}
                        className="w-full flex items-center justify-between px-3 py-2 text-[11px] text-violet-400 hover:bg-violet-500/10 transition-colors"
                      >
                        <span className="flex items-center gap-1.5">
                          <Zap className="w-3 h-3" />
                          Agent Collaboration Panel
                          {msg.isStreaming && <Loader2 className="w-3 h-3 animate-spin" />}
                        </span>
                        {msg.expertPanelOpen
                          ? <ChevronUp className="w-3 h-3" />
                          : <ChevronDown className="w-3 h-3" />
                        }
                      </button>
                      {msg.expertPanelOpen && (
                        <div className="divide-y divide-violet-500/10">
                          {msg.expertAgents.filter((a) => a.name !== "supervisor").map((agent) => (
                            <div key={agent.name} className="px-3 py-2">
                              <div className="flex items-center gap-1.5 mb-1">
                                <span>{agent.emoji}</span>
                                <span className="text-[11px] font-medium text-violet-300">{agent.label}</span>
                                {!agent.done && agent.content && (
                                  <Loader2 className="w-2.5 h-2.5 animate-spin text-violet-400 ml-auto" />
                                )}
                                {agent.done && (
                                  <Check className="w-2.5 h-2.5 text-green-400 ml-auto" />
                                )}
                              </div>
                              <p className="text-[11px] text-neutral-400 leading-relaxed whitespace-pre-wrap">
                                {agent.content || "…"}
                              </p>
                            </div>
                          ))}
                        </div>
                      )}
                    </div>
                  )}

                  <div className="flex items-center gap-2 mt-1 pl-1 flex-wrap">
                    {msg.agent && !msg.isStreaming && (
                      <p className="text-[11px] text-neutral-600">
                        {msg.isExpert ? "⚡ Expert Mode" : (AGENT_LABELS[msg.agent] ?? msg.agent)}
                        {msg.latencyMs ? ` · ${msg.latencyMs}ms` : ""}
                      </p>
                    )}
                    {msg.isEngineer && !msg.isStreaming && (
                      <span className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded-full text-[10px] font-medium bg-indigo-500/15 border border-indigo-500/30 text-indigo-400">
                        <Code2 className="w-2.5 h-2.5" />
                        Engineer Mode
                      </span>
                    )}
                    {msg.usedLiveX && !msg.isStreaming && (
                      <span className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded-full text-[10px] font-medium bg-sky-500/15 border border-sky-500/30 text-sky-400">
                        𝕏 Live from X
                      </span>
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
      </div>

      {/* Input bar */}
      <div className="border-t border-neutral-800 px-4 py-3 flex-shrink-0">
        <div className="max-w-3xl mx-auto">
          {/* Hidden file input */}
          <input
            ref={fileInputRef}
            type="file"
            accept="image/jpeg,image/png,image/gif,image/webp"
            className="hidden"
            onChange={handleFileAttach}
          />

          {/* Attached image preview */}
          {attachedFile && (
            <div className="mb-2 flex items-center gap-2 px-3 py-1.5 rounded-lg bg-violet-500/10 border border-violet-500/20">
              <img src={attachedFile.dataUrl} alt="preview" className="w-8 h-8 rounded object-cover flex-shrink-0" />
              <span className="text-violet-300 text-xs flex-1 truncate">{attachedFile.name}</span>
              <button
                onClick={() => setAttachedFile(null)}
                className="text-neutral-500 hover:text-neutral-300 transition-colors flex-shrink-0"
              >
                <X className="w-3 h-3" />
              </button>
            </div>
          )}

          {hasUrl && !attachedFile && (
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
            {/* Image attach button */}
            <button
              onClick={() => fileInputRef.current?.click()}
              disabled={isStreaming}
              title="Attach image for vision analysis"
              className={clsx(
                "flex-shrink-0 w-7 h-7 rounded-lg flex items-center justify-center transition-all mb-0.5",
                attachedFile
                  ? "bg-violet-500/20 border border-violet-500/50 text-violet-400"
                  : "text-neutral-600 hover:text-neutral-400 disabled:opacity-30"
              )}
            >
              <Paperclip className="w-3.5 h-3.5" />
            </button>
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
          <div className="flex items-center justify-between mt-1.5">
            <p className="text-[11px] text-neutral-700">
              Enter to send · Shift+Enter for new line
              {isTutor && " · Tutor mode enabled"}
              {isBodyguard && " · Bodyguard active"}
            </p>
            <div className="flex items-center gap-1.5">
              <button
                onClick={() => setExpertMode((v) => !v)}
                title="Expert Mode: 5 agents collaborate in parallel"
                className={clsx(
                  "flex items-center gap-1 px-2 py-0.5 rounded-full text-[11px] border transition-all",
                  expertMode
                    ? "bg-violet-500/20 border-violet-500/50 text-violet-300"
                    : "border-neutral-700 text-neutral-600 hover:text-neutral-400 hover:border-neutral-600"
                )}
              >
                <Zap className="w-3 h-3" />
                Expert Mode
              </button>
              {expertMode && (
                <button
                  onClick={() => setCostGuard((v) => !v)}
                  title="Cost Guard: warns before large Expert Mode queries (>50k tokens)"
                  className={clsx(
                    "flex items-center gap-1 px-2 py-0.5 rounded-full text-[11px] border transition-all",
                    costGuard
                      ? "bg-amber-500/20 border-amber-500/50 text-amber-300"
                      : "border-neutral-700 text-neutral-600 hover:text-neutral-400 hover:border-neutral-600"
                  )}
                >
                  <DollarSign className="w-3 h-3" />
                  Cost Guard
                </button>
              )}
              <button
                onClick={() => setGrokMode((v) => !v)}
                title="Think like Grok: enables Grok personality, real-time web search, and X search"
                className={clsx(
                  "flex items-center gap-1 px-2 py-0.5 rounded-full text-[11px] border transition-all",
                  grokMode
                    ? "bg-emerald-500/20 border-emerald-500/50 text-emerald-300"
                    : "border-neutral-700 text-neutral-600 hover:text-neutral-400 hover:border-neutral-600"
                )}
              >
                <Brain className="w-3 h-3" />
                Grok Mode
              </button>
              <button
                onClick={() => setEngineerMode((v) => !v)}
                title="Engineer Mode: Claude-style 4-step workflow — analysis → plan → diffs → verify"
                className={clsx(
                  "flex items-center gap-1 px-2 py-0.5 rounded-full text-[11px] border transition-all",
                  engineerMode
                    ? "bg-indigo-500/20 border-indigo-500/50 text-indigo-300"
                    : "border-neutral-700 text-neutral-600 hover:text-neutral-400 hover:border-neutral-600"
                )}
              >
                <Code2 className="w-3 h-3" />
                Engineer Mode
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
