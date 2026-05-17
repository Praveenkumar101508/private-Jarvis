"use client";

import { useState } from "react";
import { Mic, MicOff, Loader2 } from "lucide-react";
import axios from "axios";

const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
const LIVEKIT_URL = process.env.NEXT_PUBLIC_LIVEKIT_URL || "ws://localhost:7880";

type Status = "idle" | "connecting" | "connected" | "error";

export default function VoiceButton({ sessionId }: { sessionId: string }) {
  const [status, setStatus] = useState<Status>("idle");
  const [room, setRoom] = useState<any>(null);

  async function startVoice() {
    setStatus("connecting");
    try {
      const { LivekitClient } = await import("livekit-client");
      const { data } = await axios.post(`${API}/voice/token`, {
        room_name: `ira-${sessionId}`,
        participant_name: "user",
      });

      const lkRoom = new (LivekitClient as any).Room();
      await lkRoom.connect(LIVEKIT_URL, data.token);
      await lkRoom.localParticipant.setMicrophoneEnabled(true);
      setRoom(lkRoom);
      setStatus("connected");
    } catch (err) {
      console.error(err);
      setStatus("error");
    }
  }

  async function stopVoice() {
    if (room) {
      await room.disconnect();
      setRoom(null);
    }
    setStatus("idle");
  }

  return (
    <div className="flex flex-col items-center justify-center h-[75vh] gap-8">
      <div className="text-center">
        <h2 className="text-2xl font-semibold text-gray-800 mb-2">Talk to IRA</h2>
        <p className="text-gray-500 text-sm">Press the button and speak — in any language</p>
      </div>

      <button
        onClick={status === "connected" ? stopVoice : startVoice}
        disabled={status === "connecting"}
        className={`w-32 h-32 rounded-full flex items-center justify-center shadow-xl transition-all ${
          status === "connected"
            ? "bg-red-500 text-white voice-pulse scale-110"
            : status === "connecting"
            ? "bg-gray-200 text-gray-400"
            : "bg-ira-saffron text-white hover:scale-105"
        }`}
      >
        {status === "connecting" ? (
          <Loader2 size={48} className="animate-spin" />
        ) : status === "connected" ? (
          <MicOff size={48} />
        ) : (
          <Mic size={48} />
        )}
      </button>

      <div className="text-center">
        {status === "idle" && <p className="text-gray-400 text-sm">Ready to listen</p>}
        {status === "connecting" && <p className="text-ira-saffron text-sm">Connecting to IRA...</p>}
        {status === "connected" && (
          <p className="text-green-600 text-sm font-medium">Listening... tap to stop</p>
        )}
        {status === "error" && (
          <p className="text-red-500 text-sm">Connection failed. Is LiveKit running?</p>
        )}
      </div>

      <div className="text-xs text-gray-400 text-center max-w-xs">
        Voice powered by LiveKit · STT & TTS configured in .env
      </div>
    </div>
  );
}
