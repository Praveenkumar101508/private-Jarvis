"use client";

import { useState, useCallback, useRef } from "react";
import { Mic, MicOff, Phone } from "lucide-react";
import clsx from "clsx";

type Status = "idle" | "connecting" | "active" | "error";

interface Props {
  livekitUrl: string;
  livekitToken?: string;
}

export default function VoiceButton({ livekitUrl, livekitToken = "" }: Props) {
  const [status, setStatus] = useState<Status>("idle");
  const roomRef = useRef<any>(null);

  const disconnect = useCallback(async () => {
    try { await roomRef.current?.disconnect(); } catch {}
    roomRef.current = null;
    setStatus("idle");
  }, []);

  const connect = useCallback(async () => {
    if (!livekitToken) {
      setStatus("error");
      setTimeout(() => setStatus("idle"), 2_500);
      return;
    }
    setStatus("connecting");
    try {
      const { Room } = await import("livekit-client");
      const room = new Room({ adaptiveStream: true, dynacast: true });
      roomRef.current = room;
      await room.connect(livekitUrl, livekitToken, {
        autoSubscribe: true,
      });
      setStatus("active");
      room.once("disconnected", () => { roomRef.current = null; setStatus("idle"); });
    } catch (err) {
      console.error("[Voice] connect failed:", err);
      roomRef.current = null;
      setStatus("error");
      setTimeout(() => setStatus("idle"), 3_000);
    }
  }, [livekitUrl, livekitToken]);

  const toggle = useCallback(() => {
    if (status === "active") disconnect();
    else if (status === "idle") connect();
  }, [status, connect, disconnect]);

  const label =
    status === "idle"       ? "Start voice call with IRA" :
    status === "connecting" ? "Connecting…" :
    status === "active"     ? "End voice call" :
                              "Connection failed";

  return (
    <div className="relative flex items-center justify-center">
      {/* Pulse ring when active */}
      {status === "active" && (
        <>
          <span className="voice-ring absolute inline-flex w-9 h-9 rounded-full bg-emerald-400/20" />
          <span className="voice-ring absolute inline-flex w-9 h-9 rounded-full bg-emerald-400/10" style={{ animationDelay: "0.4s" }} />
        </>
      )}

      <button
        onClick={toggle}
        title={label}
        aria-label={label}
        disabled={status === "connecting"}
        className={clsx(
          "relative w-8 h-8 rounded-full flex items-center justify-center transition-all duration-200 border",
          status === "idle"       && "bg-transparent border-white/[0.1] text-white/40 hover:border-white/20 hover:text-white/70",
          status === "connecting" && "bg-orange-500/10 border-orange-400/30 text-orange-400 cursor-wait",
          status === "active"     && "bg-emerald-500 border-emerald-400 text-white shadow-lg shadow-emerald-500/30",
          status === "error"      && "bg-red-500/10 border-red-400/30 text-red-400"
        )}
      >
        {status === "connecting" ? (
          <div className="w-3.5 h-3.5 border-2 border-orange-400/30 border-t-orange-400 rounded-full animate-spin" />
        ) : status === "active" ? (
          <Phone className="w-3.5 h-3.5 fill-current" />
        ) : (
          <Mic className="w-3.5 h-3.5" />
        )}
      </button>
    </div>
  );
}
