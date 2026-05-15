"use client";

import { useState } from "react";
import ChatInterface from "@/components/ChatInterface";
import VoiceButton from "@/components/VoiceButton";
import { MessageSquare, Mic } from "lucide-react";

type Mode = "chat" | "voice";

export default function Home() {
  const [mode, setMode] = useState<Mode>("chat");
  const [sessionId] = useState(() => crypto.randomUUID());

  return (
    <main className="min-h-screen flex flex-col items-center justify-start p-4">
      {/* Header */}
      <header className="w-full max-w-2xl flex items-center justify-between py-4 mb-6">
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 rounded-full bg-ira-saffron flex items-center justify-center text-white font-bold text-lg">
            I
          </div>
          <div>
            <h1 className="text-xl font-semibold text-gray-800">IRA</h1>
            <p className="text-xs text-gray-500">Intelligent Responsive Assistant</p>
          </div>
        </div>

        {/* Mode toggle */}
        <div className="flex bg-white rounded-full p-1 shadow-sm border border-orange-100">
          <button
            onClick={() => setMode("chat")}
            className={`flex items-center gap-2 px-4 py-2 rounded-full text-sm transition-all ${
              mode === "chat"
                ? "bg-ira-saffron text-white shadow-sm"
                : "text-gray-500 hover:text-gray-700"
            }`}
          >
            <MessageSquare size={14} />
            Chat
          </button>
          <button
            onClick={() => setMode("voice")}
            className={`flex items-center gap-2 px-4 py-2 rounded-full text-sm transition-all ${
              mode === "voice"
                ? "bg-ira-saffron text-white shadow-sm"
                : "text-gray-500 hover:text-gray-700"
            }`}
          >
            <Mic size={14} />
            Voice
          </button>
        </div>
      </header>

      {/* Main content */}
      <div className="w-full max-w-2xl flex-1">
        {mode === "chat" ? (
          <ChatInterface sessionId={sessionId} />
        ) : (
          <VoiceButton sessionId={sessionId} />
        )}
      </div>

      <footer className="mt-6 text-xs text-gray-400 text-center">
        IRA speaks English, हिंदी, తెలుగు, தமிழ், ಕನ್ನಡ & more
      </footer>
    </main>
  );
}
