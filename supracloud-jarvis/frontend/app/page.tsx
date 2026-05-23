"use client";

import { useState, useEffect } from "react";
import ChatInterface from "@/components/ChatInterface";
import VoiceOrb from "@/components/VoiceOrb";
import Sidebar, { type AppMode } from "@/components/Sidebar";
import StatusBar from "@/components/StatusBar";

export default function Home() {
  const [token, setToken] = useState<string>("");
  const [livekitToken, setLivekitToken] = useState<string>("");
  const [sessionId, setSessionId] = useState<string>(() =>
    typeof crypto !== "undefined" ? crypto.randomUUID() : Math.random().toString(36).slice(2)
  );
  const [isAuthenticated, setIsAuthenticated] = useState(false);
  const [loginError, setLoginError] = useState("");
  const [username, setUsername] = useState("admin");
  const [password, setPassword] = useState("");
  const [loggingIn, setLoggingIn] = useState(false);
  const [mode, setMode] = useState<AppMode>("assistant");
  // chatKey forces ChatInterface to remount (clears messages) on New Chat
  const [chatKey, setChatKey] = useState(0);

  useEffect(() => {
    const stored = localStorage.getItem("ira_token");
    if (stored) {
      setToken(stored);
      setIsAuthenticated(true);
      fetchLivekitToken(stored);
    }
  }, []);

  const fetchLivekitToken = async (authToken: string) => {
    try {
      const res = await fetch("/api/v1/voice/token", {
        headers: { Authorization: `Bearer ${authToken}` },
      });
      if (res.ok) {
        const data = await res.json();
        setLivekitToken(data.token ?? "");
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
      localStorage.setItem("ira_token", authToken);
      setToken(authToken);
      setIsAuthenticated(true);
      await fetchLivekitToken(authToken);
    } catch {
      setLoginError("Connection failed — is IRA running?");
    } finally {
      setLoggingIn(false);
    }
  };

  const logout = () => {
    localStorage.removeItem("ira_token");
    setToken("");
    setLivekitToken("");
    setIsAuthenticated(false);
    setPassword("");
  };

  const handleNewChat = () => {
    const newId =
      typeof crypto !== "undefined"
        ? crypto.randomUUID()
        : Math.random().toString(36).slice(2);
    setSessionId(newId);
    setChatKey((k) => k + 1);
  };

  if (!isAuthenticated) {
    return (
      <div className="min-h-screen bg-neutral-950 flex items-center justify-center px-4">
        <div className="w-full max-w-sm">
          <div className="text-center mb-8">
            <div className="w-16 h-16 rounded-full bg-saffron-500/10 border border-saffron-500/30 flex items-center justify-center mx-auto mb-4">
              <span className="text-3xl select-none">✦</span>
            </div>
            <h1 className="text-2xl font-bold text-white tracking-tight">SupraCloud IRA</h1>
            <p className="text-neutral-400 text-sm mt-1">Private Sovereign AI Assistant</p>
          </div>

          <div className="bg-neutral-900 rounded-2xl p-6 border border-neutral-800 shadow-2xl">
            {loginError && (
              <div className="mb-4 p-3 rounded-lg bg-red-500/10 border border-red-500/30 text-red-400 text-sm">
                {loginError}
              </div>
            )}
            <div className="space-y-4">
              <div>
                <label className="block text-xs text-neutral-400 mb-1.5 font-medium">
                  Username
                </label>
                <input
                  type="text"
                  value={username}
                  onChange={(e) => setUsername(e.target.value)}
                  className="w-full bg-neutral-800 rounded-xl px-4 py-2.5 text-white text-sm border border-neutral-700 focus:border-saffron-500/60 focus:outline-none transition-colors"
                />
              </div>
              <div>
                <label className="block text-xs text-neutral-400 mb-1.5 font-medium">
                  Password
                </label>
                <input
                  type="password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  onKeyDown={(e) => e.key === "Enter" && login()}
                  autoFocus
                  className="w-full bg-neutral-800 rounded-xl px-4 py-2.5 text-white text-sm border border-neutral-700 focus:border-saffron-500/60 focus:outline-none transition-colors"
                />
              </div>
              <button
                onClick={login}
                disabled={loggingIn || !password.trim()}
                className="w-full bg-saffron-500 hover:bg-saffron-600 disabled:opacity-50 disabled:cursor-not-allowed text-white rounded-xl py-2.5 text-sm font-semibold transition-colors"
              >
                {loggingIn ? "Authenticating…" : "Sign In"}
              </button>
            </div>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="h-screen flex bg-neutral-950 overflow-hidden">
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
        <header className="flex items-center justify-between px-4 py-2 border-b border-neutral-800 flex-shrink-0">
          <div className="flex items-center gap-2">
            <span className="text-sm font-semibold text-white tracking-tight hidden sm:block">
              IRA
            </span>
            <span className="text-xs text-neutral-600 hidden md:block">
              Intelligent Responsive Assistant
            </span>
          </div>

          <div className="flex items-center gap-3">
            <StatusBar token={token} />
            <VoiceOrb
              livekitUrl={process.env.NEXT_PUBLIC_LIVEKIT_URL || "ws://localhost:7880"}
              livekitToken={livekitToken}
            />
            <button
              onClick={logout}
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
