"use client";

import { useState, useCallback } from "react";
import { Mic, MicOff, Loader2 } from "lucide-react";
import clsx from "clsx";

type Status = "idle" | "connecting" | "active" | "error";

interface Props {
  livekitUrl: string;
  livekitToken?: string;
}

export default function VoiceButton({ livekitUrl, livekitToken = "" }: Props) {
  const [status, setStatus] = useState<Status>("idle");

  const toggle = useCallback(async () => {
    if (status === "active") {
      setStatus("idle");
      return;
    }
    if (!livekitToken) {
      // No token yet — show brief error state
      setStatus("error");
      setTimeout(() => setStatus("idle"), 2_000);
      return;
    }

    setStatus("connecting");
    try {
      // Dynamic import keeps LiveKit out of the SSR bundle
      const { Room } = await import("livekit-client");
      const room = new Room();
      await room.connect(livekitUrl, livekitToken);
      setStatus("active");
      room.once("disconnected", () => setStatus("idle"));
    } catch (err) {
      console.error("[VoiceButton] LiveKit connect failed:", err);
      setStatus("error");
      setTimeout(() => setStatus("idle"), 3_000);
    }
  }, [status, livekitUrl, livekitToken]);

  const label =
    status === "idle"       ? "Start voice conversation" :
    status === "connecting" ? "Connecting to IRA…" :
    status === "active"     ? "Listening — click to stop" :
                              "Connection failed — retrying";

  return (
    <button
      onClick={toggle}
      title={label}
      aria-label={label}
      className={clsx(
        "w-9 h-9 rounded-full flex items-center justify-center transition-all duration-200 border",
        status === "idle"       && "bg-neutral-800 border-neutral-700 text-neutral-400 hover:border-neutral-600 hover:text-neutral-200",
        status === "connecting" && "bg-saffron-500/10 border-saffron-500/40 text-saffron-400",
        status === "active"     && "bg-saffron-500 border-saffron-400 text-white shadow-lg shadow-saffron-500/25 animate-pulse",
        status === "error"      && "bg-red-500/10 border-red-500/40 text-red-400"
      )}
    >
      {status === "connecting" ? (
        <Loader2 className="w-4 h-4 animate-spin" />
      ) : status === "active" ? (
        <Mic className="w-4 h-4" />
      ) : (
        <MicOff className="w-4 h-4" />
      )}
    </button>
  );
}
