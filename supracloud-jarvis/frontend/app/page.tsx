"use client";

import { useState, useEffect } from "react";
import ChatInterface from "@/components/ChatInterface";
import VoiceButton from "@/components/VoiceButton";
import StatusBar from "@/components/StatusBar";

export default function Home() {
  const [token, setToken] = useState<string>("");
  const [sessionId] = useState<string>(() =>
    typeof crypto !== "undefined" ? crypto.randomUUID() : Math.random().toString(36).slice(2)
  );
  const [isAuthenticated, setIsAuthenticated] = useState(false);
  const [loginError, setLoginError] = useState("");
  const [username, setUsername] = useState("admin");
  const [password, setPassword] = useState("");
  const [loggingIn, setLoggingIn] = useState(false);

  // Restore token from localStorage on mount
  useEffect(() => {
    const stored = localStorage.getItem("ira_token");
    if (stored) {
      setToken(stored);
      setIsAuthenticated(true);
    }
  }, []);

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
      localStorage.setItem("ira_token", data.access_token);
      setToken(data.access_token);
      setIsAuthenticated(true);
    } catch {
      setLoginError("Connection failed — is IRA running?");
    } finally {
      setLoggingIn(false);
    }
  };

  const logout = () => {
    localStorage.removeItem("ira_token");
    setToken("");
    setIsAuthenticated(false);
    setPassword("");
  };

  if (!isAuthenticated) {
    return (
      <div className="min-h-screen bg-neutral-950 flex items-center justify-center px-4">
        <div className="w-full max-w-sm">
          {/* Logo */}
          <div className="text-center mb-8">
            <div className="w-16 h-16 rounded-full bg-saffron-500/10 border border-saffron-500/30 flex items-center justify-center mx-auto mb-4">
              <span className="text-3xl select-none">✦</span>
            </div>
            <h1 className="text-2xl font-bold text-white tracking-tight">SupraCloud IRA</h1>
            <p className="text-neutral-400 text-sm mt-1">Private Sovereign AI Assistant</p>
          </div>

          {/* Login card */}
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
    <div className="h-screen flex flex-col bg-neutral-950 overflow-hidden">
      {/* Top bar */}
      <header className="flex items-center justify-between px-4 py-2.5 border-b border-neutral-800 flex-shrink-0">
        <div className="flex items-center gap-2">
          <div className="w-7 h-7 rounded-full bg-saffron-500/20 border border-saffron-500/40 flex items-center justify-center select-none">
            <span className="text-sm">✦</span>
          </div>
          <span className="text-sm font-semibold text-white tracking-tight">IRA</span>
          <span className="text-xs text-neutral-500 hidden sm:block">Intelligent Responsive Assistant</span>
        </div>

        <div className="flex items-center gap-3">
          <StatusBar token={token} />
          <VoiceButton
            livekitUrl={process.env.NEXT_PUBLIC_LIVEKIT_URL || "ws://localhost:7880"}
          />
          <button
            onClick={logout}
            className="text-xs text-neutral-500 hover:text-neutral-300 transition-colors px-2 py-1 rounded-lg hover:bg-neutral-800"
          >
            Sign out
          </button>
        </div>
      </header>

      {/* Main chat area */}
      <main className="flex-1 overflow-hidden">
        <ChatInterface sessionId={sessionId} token={token} />
      </main>
    </div>
  );
}
