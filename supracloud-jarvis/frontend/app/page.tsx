"use client";

import { useState, useEffect } from "react";
import ChatInterface from "@/components/ChatInterface";
import VoiceOrb from "@/components/VoiceOrb";
import VoiceConsole from "@/components/VoiceConsole";
import Sidebar, { type AppMode } from "@/components/Sidebar";
import StatusBar from "@/components/StatusBar";
import { useAuthStore, useUIStore, useChatStore } from "@/lib/store";

export default function Home() {
  const { token, isAuthenticated, livekitToken, livekitUrl, setToken, setLivekitToken, logout } = useAuthStore();
  const { mode, setMode } = useUIStore();
  const { newSession, sessionId } = useChatStore();

  // Fix #101: detect ?mode=voice from the PWA manifest shortcut
  const [autoVoice, setAutoVoice] = useState(false);
  const [loginError, setLoginError] = useState("");
  const [username, setUsername] = useState("admin");
  const [password, setPassword] = useState("");
  const [loggingIn, setLoggingIn] = useState(false);
  // chatKey forces ChatInterface to remount (clears messages) on New Chat
  const [chatKey, setChatKey] = useState(0);

  useEffect(() => {
    // Fix #101: read ?mode=voice query param set by the PWA manifest shortcut
    // so the VoiceOrb auto-connects when the user launches IRA in voice mode.
    if (typeof window !== "undefined") {
      const params = new URLSearchParams(window.location.search);
      if (params.get("mode") === "voice") setAutoVoice(true);
    }
  }, []);

  useEffect(() => {
    // Zustand persist middleware already restores token from sessionStorage.
    // Fetch LiveKit token if we already have an auth token on mount.
    if (token) fetchLivekitToken(token);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const fetchLivekitToken = async (authToken: string) => {
    try {
      const res = await fetch("/api/v1/voice/token", {
        headers: { Authorization: `Bearer ${authToken}` },
      });
      if (res.ok) {
        const data = await res.json();
        // Fix #97: use the URL returned by the server instead of a hardcoded
        // env var so the frontend works correctly whether pointing at localhost,
        // a LAN IP, or a production domain without a Next.js rebuild.
        setLivekitToken(data.token ?? "", data.livekit_url ?? "");
      }
    } catch {
      console.warn("[IRA] LiveKit token fetch failed — voice disabled");
    }
  };

  const login = async () => {
    if (!password.trim()) return;
    setLoggingIn(true);
    setLoginError("");
    try {
      const form = new FormData();
      form.append("username", username);
      form.append("password", password);

      const res = await fetch("/auth/token", { method: "POST", body: form });
      if (!res.ok) {
        setLoginError("Invalid credentials. Please try again.");
        return;
      }
      const data = await res.json();
      const authToken = data.access_token;
      setToken(authToken);  // Zustand persist handles sessionStorage
      await fetchLivekitToken(authToken);
    } catch {
      setLoginError("Connection failed — is IRA running?");
    } finally {
      setLoggingIn(false);
    }
  };

  const handleLogout = () => {
    logout();  // clears Zustand state; persist middleware removes from sessionStorage
    setPassword("");
  };

  const handleNewChat = () => {
    newSession();
    setChatKey((k) => k + 1);
  };

  if (!isAuthenticated) {
    return (
      <div className="min-h-screen flex items-center justify-center px-4">
        <div className="w-full max-w-sm animate-fade-in">
          <div className="text-center mb-8">
            <div className="relative w-20 h-20 rounded-full bg-saffron-500/10 border border-saffron-500/30 ira-orb-glow animate-float-soft flex items-center justify-center mx-auto mb-5">
              <span className="text-4xl select-none" aria-hidden="true">✦</span>
              {/* Live pulse ring */}
              <span className="absolute -top-0.5 -right-0.5 flex h-3 w-3" aria-hidden="true">
                <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-60" />
                <span className="relative inline-flex rounded-full h-3 w-3 bg-emerald-500 border-2 border-neutral-950" />
              </span>
            </div>
            <h1 className="text-3xl font-bold tracking-tight ira-gradient-text">SupraCloud IRA</h1>
            <p className="text-neutral-400 text-sm mt-1.5">
              Your AI. Your hardware. Your rules.
            </p>
            {/* Local-first identity badge */}
            <div className="inline-flex items-center gap-1.5 mt-3 px-2.5 py-1 rounded-full bg-emerald-500/10 border border-emerald-500/25 text-emerald-400 text-[11px] font-medium">
              <span className="w-1.5 h-1.5 rounded-full bg-emerald-400" aria-hidden="true" />
              100% local &amp; private — nothing leaves this machine
            </div>
            {/* Capability pills */}
            <div className="flex flex-wrap justify-center gap-1.5 mt-3">
              {["Qwen3 · Reasoning", "Real-time Search", "Expert Mode", "Voice", "Vision", "DeepSearch"].map((cap) => (
                <span key={cap} className="px-2 py-0.5 rounded-full text-[10px] ira-glass text-neutral-400">
                  {cap}
                </span>
              ))}
            </div>
          </div>

          <div className="ira-glass rounded-2xl p-6 shadow-panel">
            {loginError && (
              <div role="alert" className="mb-4 p-3 rounded-lg bg-red-500/10 border border-red-500/30 text-red-400 text-sm flex items-start gap-2">
                <span className="text-base leading-none mt-0.5" aria-hidden="true">⚠</span>
                <span>{loginError}</span>
              </div>
            )}
            <div className="space-y-4">
              <div>
                <label htmlFor="ira-username" className="block text-xs text-neutral-400 mb-1.5 font-medium tracking-wide uppercase">
                  Username
                </label>
                <input
                  id="ira-username"
                  type="text"
                  autoComplete="username"
                  value={username}
                  onChange={(e) => setUsername(e.target.value)}
                  className="w-full bg-neutral-900/70 rounded-xl px-4 py-2.5 text-white text-sm border border-neutral-700/80 focus:border-saffron-500/60 focus:outline-none transition-colors"
                />
              </div>
              <div>
                <label htmlFor="ira-password" className="block text-xs text-neutral-400 mb-1.5 font-medium tracking-wide uppercase">
                  Password
                </label>
                <input
                  id="ira-password"
                  type="password"
                  autoComplete="current-password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  onKeyDown={(e) => e.key === "Enter" && login()}
                  autoFocus
                  className="w-full bg-neutral-900/70 rounded-xl px-4 py-2.5 text-white text-sm border border-neutral-700/80 focus:border-saffron-500/60 focus:outline-none transition-colors"
                />
              </div>
              <button
                onClick={login}
                disabled={loggingIn || !password.trim()}
                className="w-full bg-gradient-to-r from-saffron-500 to-saffron-600 hover:from-saffron-400 hover:to-saffron-500 shadow-glow-saffron active:scale-[0.98] disabled:opacity-50 disabled:cursor-not-allowed disabled:shadow-none text-white rounded-xl py-2.5 text-sm font-semibold transition-all"
              >
                {loggingIn ? (
                  <span className="flex items-center justify-center gap-2">
                    <svg className="animate-spin h-3.5 w-3.5" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" aria-hidden="true">
                      <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"/>
                      <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"/>
                    </svg>
                    Authenticating…
                  </span>
                ) : "Sign In"}
              </button>
            </div>
            <p className="text-center text-[11px] text-neutral-600 mt-4">
              Sovereign · Private · Self-Hosted — built by Praveen Kamineti
            </p>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="h-screen flex overflow-hidden">
      {/* Collapsible sidebar */}
      <Sidebar
        mode={mode}
        onModeChange={setMode}
        onNewChat={handleNewChat}
        token={token}
      />

      {/* Main column: top bar + chat */}
      <div className="flex-1 flex flex-col min-w-0">
        {/* Slim top bar */}
        <header className="flex items-center justify-between px-4 py-2 border-b border-white/[0.06] bg-neutral-950/60 backdrop-blur-md flex-shrink-0">
          <div className="flex items-center gap-2.5">
            {/* Brand mark */}
            <div className="w-6 h-6 rounded-full bg-saffron-500/15 border border-saffron-500/30 flex items-center justify-center select-none flex-shrink-0">
              <span className="text-[10px]">✦</span>
            </div>
            <span className="text-sm font-semibold text-white tracking-tight hidden sm:block">
              IRA
            </span>
            {/* Live pulse indicator */}
            <span className="flex items-center gap-1 hidden sm:flex">
              <span className="relative flex h-1.5 w-1.5">
                <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75" />
                <span className="relative inline-flex rounded-full h-1.5 w-1.5 bg-emerald-500" />
              </span>
              <span className="text-[10px] text-emerald-600 font-medium hidden lg:block">live</span>
            </span>
            {/* Model badge */}
            <span className="hidden md:inline-flex items-center px-1.5 py-0.5 rounded-md text-[10px] ira-glass text-neutral-500 font-mono">
              Qwen3 · v1.0
            </span>
            {/* Local-first privacy indicator */}
            <span
              className="hidden md:inline-flex items-center gap-1 px-1.5 py-0.5 rounded-md text-[10px] bg-emerald-500/10 border border-emerald-500/25 text-emerald-500"
              title="All inference runs on this machine — no cloud calls without your consent"
            >
              🔒 Local
            </span>
            <span className="text-xs text-neutral-600 hidden xl:block">
              Intelligent Responsive Assistant
            </span>
          </div>

          <div className="flex items-center gap-3">
            <StatusBar token={token} />
            {/* Browser-native voice is the default working path on the native
                Shadow PC; LiveKit is legacy, selectable via NEXT_PUBLIC_VOICE_TRANSPORT=livekit. */}
            {(process.env.NEXT_PUBLIC_VOICE_TRANSPORT || "browser") === "livekit" ? (
              <VoiceOrb
                livekitUrl={livekitUrl || process.env.NEXT_PUBLIC_LIVEKIT_URL || "ws://localhost:7880"}
                livekitToken={livekitToken}
                autoConnect={autoVoice}
              />
            ) : (
              <VoiceConsole token={token} sessionId={sessionId} />
            )}
            <button
              onClick={handleLogout}
              className="text-xs text-neutral-500 hover:text-neutral-300 transition-colors px-2 py-1 rounded-lg hover:bg-neutral-800"
            >
              Sign out
            </button>
          </div>
        </header>

        {/* Chat area */}
        <main className="flex-1 overflow-hidden">
          <ChatInterface
            key={chatKey}
            sessionId={sessionId}
            token={token}
            mode={mode}
          />
        </main>
      </div>
    </div>
  );
}
