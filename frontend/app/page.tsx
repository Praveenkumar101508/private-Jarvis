"use client";

import { useState, useEffect } from "react";
import ChatInterface from "@/components/ChatInterface";
import VoiceButton from "@/components/VoiceButton";

export default function Home() {
  const [token, setToken] = useState("");
  const [livekitToken, setLivekitToken] = useState("");
  const [isReady, setIsReady] = useState(false);
  const [authError, setAuthError] = useState("");
  const [sessionId] = useState(() =>
    typeof crypto !== "undefined" ? crypto.randomUUID() : Math.random().toString(36).slice(2)
  );

  // Auto-login on mount using stored token or env credentials
  useEffect(() => {
    const stored = localStorage.getItem("ira_token");
    if (stored) {
      setToken(stored);
      setIsReady(true);
      fetchLivekitToken(stored);
    } else {
      autoLogin();
    }
  }, []);

  const autoLogin = async () => {
    try {
      const form = new FormData();
      form.append("username", "Ira_admin");
      form.append("password", "Pk24ks15");
      const res = await fetch("/auth/token", { method: "POST", body: form });
      if (!res.ok) {
        setAuthError("Auth failed — check IRA is running");
        return;
      }
      const data = await res.json();
      const t = data.access_token;
      localStorage.setItem("ira_token", t);
      setToken(t);
      setIsReady(true);
      fetchLivekitToken(t);
    } catch {
      setAuthError("Cannot reach IRA API — is it running on port 8000?");
    }
  };

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
      // voice optional
    }
  };

  const logout = () => {
    localStorage.removeItem("ira_token");
    setToken("");
    setLivekitToken("");
    setIsReady(false);
    setAuthError("");
    autoLogin();
  };

  if (!isReady) {
    return (
      <div className="min-h-screen bg-[#0d0d0d] flex items-center justify-center">
        <div className="text-center">
          {authError ? (
            <>
              <div className="w-12 h-12 rounded-full bg-red-500/10 border border-red-500/30 flex items-center justify-center mx-auto mb-4">
                <span className="text-red-400 text-lg">!</span>
              </div>
              <p className="text-red-400 text-sm mb-3">{authError}</p>
              <button
                onClick={autoLogin}
                className="text-xs text-neutral-400 hover:text-white border border-neutral-700 hover:border-neutral-500 px-4 py-2 rounded-lg transition-colors"
              >
                Retry
              </button>
            </>
          ) : (
            <>
              <div className="w-8 h-8 border-2 border-white/20 border-t-white/80 rounded-full animate-spin mx-auto mb-3" />
              <p className="text-neutral-500 text-sm">Starting IRA…</p>
            </>
          )}
        </div>
      </div>
    );
  }

  return (
    <div className="h-screen flex flex-col bg-[#0d0d0d] overflow-hidden">
      {/* Top bar — minimal, like Claude */}
      <header className="flex items-center justify-between px-5 py-3 border-b border-white/[0.06] flex-shrink-0">
        <div className="flex items-center gap-2.5">
          {/* IRA logo — glowing dot */}
          <div className="relative flex items-center justify-center">
            <div className="w-2 h-2 rounded-full bg-emerald-400 shadow-[0_0_6px_2px_rgba(52,211,153,0.5)]" />
          </div>
          <span className="text-sm font-medium text-white/90 tracking-tight">IRA</span>
          <span className="text-xs text-white/25 hidden sm:block">· SupraCloud</span>
        </div>

        <div className="flex items-center gap-3">
          <VoiceButton
            livekitUrl={process.env.NEXT_PUBLIC_LIVEKIT_URL || "ws://localhost:7880"}
            livekitToken={livekitToken}
          />
          <button
            onClick={logout}
            className="text-[11px] text-white/25 hover:text-white/50 transition-colors"
            title="Reset session"
          >
            Reset
          </button>
        </div>
      </header>

      <main className="flex-1 overflow-hidden">
        <ChatInterface sessionId={sessionId} token={token} />
      </main>
    </div>
  );
}
