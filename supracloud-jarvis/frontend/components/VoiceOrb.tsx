"use client";

import { useState, useEffect, useRef, useCallback } from "react";
import { Mic, MicOff, Volume2 } from "lucide-react";
import clsx from "clsx";

type VoiceState = "idle" | "connecting" | "listening" | "thinking" | "speaking";

interface Props {
  livekitUrl: string;
  livekitToken: string;
  // Fix #101: when true, automatically connect once the token is available
  // (used by the ?mode=voice PWA shortcut in manifest.json).
  autoConnect?: boolean;
}

export default function VoiceOrb({ livekitUrl, livekitToken, autoConnect = false }: Props) {
  const [voiceState, setVoiceState] = useState<VoiceState>("idle");
  const [room, setRoom] = useState<any>(null);
  const [error, setError] = useState("");
  // Fix #101: prevent double-connect if effect fires more than once
  const autoConnectedRef = useRef(false);

  const isActive = voiceState !== "idle";

  const handleToggle = useCallback(async () => {
    if (isActive) {
      // Disconnect
      if (room) {
        await room.disconnect();
        setRoom(null);
      }
      setVoiceState("idle");
      setError("");
      return;
    }

    if (!livekitToken) {
      setError("Voice unavailable — no token.");
      return;
    }

    setVoiceState("connecting");
    setError("");

    try {
      const { Room, RoomEvent } = await import("livekit-client");
      const r = new Room({
        adaptiveStream: true,
        dynacast: true,
      });

      r.on(RoomEvent.Connected, () => setVoiceState("listening"));
      r.on(RoomEvent.Disconnected, () => {
        setVoiceState("idle");
        setRoom(null);
      });
      r.on(RoomEvent.TrackSubscribed, () => setVoiceState("speaking"));
      r.on(RoomEvent.TrackUnsubscribed, () => {
        if (r.state === "connected") setVoiceState("listening");
      });
      r.on(RoomEvent.ConnectionStateChanged, (state) => {
        if (state === "connecting") setVoiceState("connecting");
      });

      await r.connect(livekitUrl, livekitToken, {
        autoSubscribe: true,
      });
      await r.localParticipant.setMicrophoneEnabled(true);
      setRoom(r);
    } catch (e: any) {
      setError("Mic error — check browser permissions.");
      setVoiceState("idle");
    }
  }, [livekitUrl, livekitToken, isActive, room]);

  // Fix #101: auto-connect when ?mode=voice is in the URL (PWA shortcut).
  // Wait until the token is available before connecting.
  useEffect(() => {
    if (autoConnect && livekitToken && !isActive && !autoConnectedRef.current) {
      autoConnectedRef.current = true;
      handleToggle();
    }
  }, [autoConnect, livekitToken, isActive, handleToggle]);

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      if (room) room.disconnect();
    };
  }, [room]);

  const stateLabel: Record<VoiceState, string> = {
    idle:       "",
    connecting: "Connecting…",
    listening:  "Listening",
    thinking:   "Thinking…",
    speaking:   "Speaking",
  };

  const orbColor: Record<VoiceState, string> = {
    idle:       "bg-neutral-800 border-neutral-700 text-neutral-400",
    connecting: "bg-neutral-800 border-saffron-500/40 text-saffron-400",
    listening:  "bg-saffron-500/20 border-saffron-500 text-saffron-400",
    thinking:   "bg-indigo-500/20 border-indigo-500 text-indigo-400",
    speaking:   "bg-green-500/20 border-green-500 text-green-400",
  };

  const ringColor: Record<VoiceState, string> = {
    idle:       "",
    connecting: "bg-saffron-500/30",
    listening:  "bg-saffron-500/40",
    thinking:   "bg-indigo-500/40",
    speaking:   "bg-green-500/40",
  };

  return (
    <div className="relative flex flex-col items-center">
      {/* Pulse rings — shown when active */}
      {isActive && (
        <>
          <span
            className={clsx(
              "absolute inset-0 rounded-full animate-pulse-ring",
              ringColor[voiceState],
            )}
          />
          <span
            className={clsx(
              "absolute inset-0 rounded-full animate-pulse-ring-d",
              ringColor[voiceState],
            )}
          />
        </>
      )}

      {/* Orb button */}
      <button
        onClick={handleToggle}
        title={isActive ? `IRA voice — ${stateLabel[voiceState]}` : "Start voice"}
        className={clsx(
          "relative z-10 w-8 h-8 rounded-full border flex items-center justify-center transition-all duration-300",
          orbColor[voiceState],
          isActive ? "shadow-lg" : "hover:border-neutral-500 hover:text-neutral-200",
        )}
      >
        {voiceState === "speaking" ? (
          <Volume2 className="w-3.5 h-3.5" />
        ) : isActive ? (
          <Mic className="w-3.5 h-3.5" />
        ) : (
          <Mic className="w-3.5 h-3.5" />
        )}
      </button>

      {/* State label — shown below orb when active */}
      {stateLabel[voiceState] && (
        <span className="absolute -bottom-4 text-[10px] text-neutral-500 whitespace-nowrap">
          {stateLabel[voiceState]}
        </span>
      )}

      {/* Error tooltip */}
      {error && (
        <div className="absolute top-10 right-0 z-50 bg-red-900/90 border border-red-500/50 text-red-300 text-xs rounded-lg px-3 py-2 w-48 shadow-xl">
          {error}
        </div>
      )}
    </div>
  );
}
