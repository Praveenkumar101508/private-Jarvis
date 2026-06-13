"use client";

/**
 * VoiceConsole — the browser-native voice loop (no LiveKit).
 *
 * Flow:  arm → wait for activation (wake word "hey ira" OR double-clap) → capture
 * the command utterance → transcribe (sovereign faster-whisper via /voice/transcribe,
 * or opt-in Web Speech) → if the speaker is not the owner, refuse → else stream the
 * reply from /chat/stream and speak each sentence through /voice/say with a gapless
 * audio queue → return to listening. Speaking is interruptible (barge-in).
 *
 * Everything runs in the browser against the local IRA API — no token, no LiveKit
 * server, so the Shadow-PC "Voice unavailable — no token" failure mode is gone.
 *
 * The visual orb mirrors VoiceOrb's idle/listening/thinking/speaking states.
 *
 * Config (frontend reads NEXT_PUBLIC_* — only those are exposed to the browser):
 *   NEXT_PUBLIC_VOICE_ACTIVATION  wakeword | clap        (default wakeword)
 *   NEXT_PUBLIC_WAKE_WORD         trigger phrase         (default "hey ira")
 *   NEXT_PUBLIC_VOICE_STT         whisper | webspeech    (default whisper, sovereign)
 */

import { useEffect, useRef, useState, useCallback } from "react";
import { Mic, Volume2, Loader2 } from "lucide-react";
import clsx from "clsx";

type VoiceState = "idle" | "listening" | "thinking" | "speaking";

interface Props {
  token: string;
  sessionId: string;
}

// ── Tunable constants ─────────────────────────────────────────────────────────
// Clap activation (Web Audio RMS spike) — ported from the native thresholds.
const CLAP_SPIKE_RATIO = 7.0;        // instantaneous RMS / rolling baseline
const CLAP_COOLDOWN_S = 0.45;        // ignore further spikes within this window
const CLAP_DOUBLE_GAP_MIN_S = 0.05;  // two claps must be ≥ this far apart
const CLAP_DOUBLE_GAP_MAX_S = 0.35;  // …and ≤ this far apart

// Command-capture endpointing (whisper path).
const UTTERANCE_MAX_MS = 8000;       // hard cap on a single command
const SILENCE_HANG_MS = 800;         // stop after this much trailing silence
const SPEECH_RMS = 0.015;            // RMS above this counts as speech
const MIN_SPEECH_MS = 300;           // require this much speech before silence ends it

// Barge-in: the user speaking over IRA stops playback immediately.
const BARGE_IN_RMS = 0.06;
const BARGE_IN_MS = 150;             // sustained speech needed to trigger barge-in

// Frontend env (NEXT_PUBLIC_* only).
const WAKE_WORD = (process.env.NEXT_PUBLIC_WAKE_WORD || "hey ira").toLowerCase();
const STT_MODE = (process.env.NEXT_PUBLIC_VOICE_STT || "whisper").toLowerCase();
// Sovereign default: wake word uses the browser's Web Speech (audio leaves the box),
// so when STT is the sovereign whisper path, default activation to clap (Web Audio,
// fully local). An explicit NEXT_PUBLIC_VOICE_ACTIVATION always wins.
const ACTIVATION = (
  process.env.NEXT_PUBLIC_VOICE_ACTIVATION || (STT_MODE === "whisper" ? "clap" : "wakeword")
).toLowerCase();
// Wake word AND webspeech both route audio through the browser vendor — NOT private.
const USES_CLOUD_SPEECH = ACTIVATION === "wakeword" || STT_MODE === "webspeech";

// ── Small helpers ─────────────────────────────────────────────────────────────
function authHeader(token: string): Record<string, string> {
  return token ? { Authorization: `Bearer ${token}` } : {};
}

function pickRecorderMime(): string {
  const MR = (typeof window !== "undefined" ? window.MediaRecorder : undefined) as
    | typeof MediaRecorder
    | undefined;
  if (!MR) return "";
  for (const m of ["audio/webm;codecs=opus", "audio/webm", "audio/ogg;codecs=opus"]) {
    if (MR.isTypeSupported(m)) return m;
  }
  return "";
}

function rmsOf(analyser: AnalyserNode, buf: Uint8Array<ArrayBuffer>): number {
  analyser.getByteTimeDomainData(buf);
  let sum = 0;
  for (let i = 0; i < buf.length; i++) {
    const v = (buf[i] - 128) / 128;
    sum += v * v;
  }
  return Math.sqrt(sum / buf.length);
}

// Split off the first complete sentence (terminator followed by whitespace) so we
// can start synthesising before the whole reply has streamed in.
function takeSentence(s: string): { sentence: string; rest: string } | null {
  const m = s.match(/^([\s\S]*?[.!?…])\s+([\s\S]*)$/);
  if (m) return { sentence: m[1].trim(), rest: m[2] };
  return null;
}

export default function VoiceConsole({ token, sessionId }: Props) {
  const [voiceState, setVoiceState] = useState<VoiceState>("idle");
  const [error, setError] = useState("");

  // Mic + audio graph
  const micRef = useRef<MediaStream | null>(null);
  const acRef = useRef<AudioContext | null>(null);
  const analyserRef = useRef<AnalyserNode | null>(null);
  const tdRef = useRef<Uint8Array<ArrayBuffer>>(new Uint8Array(2048));

  // Activation / capture handles
  const recogRef = useRef<any>(null);
  const watchRafRef = useRef<number | null>(null);
  const bargeRafRef = useRef<number | null>(null);

  // Playback queue (gapless)
  const playheadRef = useRef(0);
  const sourcesRef = useRef<Set<AudioBufferSourceNode>>(new Set());
  const ttsQueueRef = useRef<string[]>([]);
  const ttsBusyRef = useRef(false);
  const streamDoneRef = useRef(true);
  const chatAbortRef = useRef<AbortController | null>(null);

  // Mirror of voiceState for use inside async loops / callbacks (avoids stale closure)
  const stateRef = useRef<VoiceState>("idle");
  const armedRef = useRef(false);

  // Props mirrored into refs so async callbacks never close over a stale token or
  // sessionId (sessionId changes on "New Chat" while this component stays mounted).
  const tokenRef = useRef(token);
  tokenRef.current = token;
  const sessionRef = useRef(sessionId);
  sessionRef.current = sessionId;

  // armLoop lives in a ref so the memoised callbacks below always invoke the latest
  // closure (it depends on callbacks defined further down).
  const armLoopRef = useRef<() => void>(() => {});

  const setState = useCallback((s: VoiceState) => {
    stateRef.current = s;
    setVoiceState(s);
  }, []);

  // ── Audio setup ───────────────────────────────────────────────────────────
  const ensureAudio = useCallback(async () => {
    if (!micRef.current) {
      micRef.current = await navigator.mediaDevices.getUserMedia({
        audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true },
      });
    }
    if (!acRef.current) {
      const AC = window.AudioContext || (window as any).webkitAudioContext;
      const ac: AudioContext = new AC();
      const analyser = ac.createAnalyser();
      analyser.fftSize = 2048;
      ac.createMediaStreamSource(micRef.current).connect(analyser);
      acRef.current = ac;
      analyserRef.current = analyser;
      tdRef.current = new Uint8Array(analyser.fftSize);
    }
    if (acRef.current.state === "suspended") await acRef.current.resume();
  }, []);

  // ── Activation watchers ───────────────────────────────────────────────────
  const stopWatch = useCallback(() => {
    if (watchRafRef.current !== null) {
      cancelAnimationFrame(watchRafRef.current);
      watchRafRef.current = null;
    }
    if (recogRef.current) {
      try {
        recogRef.current.onend = null;
        recogRef.current.stop();
      } catch {
        /* ignore */
      }
      recogRef.current = null;
    }
  }, []);

  const startWakeWord = useCallback((onActivate: () => void) => {
    const SR = (window as any).SpeechRecognition || (window as any).webkitSpeechRecognition;
    if (!SR) {
      setError("Wake word needs Chrome's Web Speech API. Use clap mode instead.");
      return;
    }
    const r = new SR();
    r.continuous = true;
    r.interimResults = true;
    r.lang = "en-US";
    r.onresult = (e: any) => {
      let said = "";
      for (let i = e.resultIndex; i < e.results.length; i++) said += e.results[i][0].transcript;
      if (said.toLowerCase().includes(WAKE_WORD)) {
        stopWatch();
        onActivate();
      }
    };
    // Chrome ends recognition after a pause — restart while we're still waiting.
    r.onend = () => {
      if (recogRef.current === r && stateRef.current === "listening") {
        try {
          r.start();
        } catch {
          /* already started */
        }
      }
    };
    r.onerror = () => {};
    recogRef.current = r;
    try {
      r.start();
    } catch {
      /* ignore */
    }
  }, [stopWatch]);

  const startClap = useCallback((onActivate: () => void) => {
    const analyser = analyserRef.current!;
    const buf = tdRef.current;
    let baseline = 0.01;
    let firstClapAt = -Infinity;
    let lastSpikeAt = -Infinity;
    const loop = () => {
      if (!armedRef.current || stateRef.current !== "listening") return;
      const now = performance.now() / 1000;
      const rms = rmsOf(analyser, buf);
      const isSpike = rms > baseline * CLAP_SPIKE_RATIO && now - lastSpikeAt > CLAP_COOLDOWN_S;
      if (isSpike) {
        lastSpikeAt = now;
        const gap = now - firstClapAt;
        if (gap >= CLAP_DOUBLE_GAP_MIN_S && gap <= CLAP_DOUBLE_GAP_MAX_S) {
          firstClapAt = -Infinity;
          stopWatch();
          onActivate();
          return;
        }
        firstClapAt = now;
      } else {
        // Slowly adapt the baseline to ambient noise when not mid-clap.
        baseline = baseline * 0.95 + rms * 0.05;
      }
      watchRafRef.current = requestAnimationFrame(loop);
    };
    watchRafRef.current = requestAnimationFrame(loop);
  }, [stopWatch]);

  // ── Command capture ───────────────────────────────────────────────────────
  const recognizeOnce = useCallback((): Promise<string> => {
    return new Promise((resolve) => {
      const SR = (window as any).SpeechRecognition || (window as any).webkitSpeechRecognition;
      if (!SR) return resolve("");
      const r = new SR();
      r.continuous = false;
      r.interimResults = false;
      r.lang = "en-US";
      let text = "";
      r.onresult = (e: any) => {
        text = e.results[0][0].transcript;
      };
      r.onend = () => resolve(text);
      r.onerror = () => resolve(text);
      try {
        r.start();
      } catch {
        resolve("");
      }
    });
  }, []);

  const captureUtteranceBlob = useCallback((): Promise<Blob> => {
    return new Promise((resolve) => {
      const stream = micRef.current!;
      const analyser = analyserRef.current!;
      const buf = tdRef.current;
      const mime = pickRecorderMime();
      const rec = mime ? new MediaRecorder(stream, { mimeType: mime }) : new MediaRecorder(stream);
      const chunks: BlobPart[] = [];
      rec.ondataavailable = (e) => {
        if (e.data.size) chunks.push(e.data);
      };
      rec.onstop = () => resolve(new Blob(chunks, { type: rec.mimeType || "audio/webm" }));
      rec.start(100);

      let speechMs = 0;
      let silenceMs = 0;
      let elapsed = 0;
      let last = performance.now();
      const tick = () => {
        if (rec.state !== "recording") return;
        const now = performance.now();
        const dt = now - last;
        last = now;
        elapsed += dt;
        const rms = rmsOf(analyser, buf);
        if (rms > SPEECH_RMS) {
          speechMs += dt;
          silenceMs = 0;
        } else if (speechMs > 0) {
          silenceMs += dt;
        }
        const ended =
          (speechMs >= MIN_SPEECH_MS && silenceMs >= SILENCE_HANG_MS) || elapsed >= UTTERANCE_MAX_MS;
        if (ended) {
          rec.stop();
          return;
        }
        requestAnimationFrame(tick);
      };
      requestAnimationFrame(tick);
    });
  }, []);

  // ── TTS playback (gapless) ────────────────────────────────────────────────
  const maybeFinishSpeaking = useCallback(() => {
    if (
      streamDoneRef.current &&
      ttsQueueRef.current.length === 0 &&
      !ttsBusyRef.current &&
      sourcesRef.current.size === 0 &&
      stateRef.current === "speaking"
    ) {
      // Turn complete — go back to waiting for the next activation.
      setState("listening");
      armLoopRef.current();
    }
  }, [setState]); // armLoop defined below; hoisted via function declaration

  const schedulePlayback = useCallback(
    async (wav: ArrayBuffer) => {
      const ac = acRef.current;
      if (!ac) return;
      const audioBuf = await ac.decodeAudioData(wav);
      const src = ac.createBufferSource();
      src.buffer = audioBuf;
      src.connect(ac.destination);
      const startAt = Math.max(ac.currentTime, playheadRef.current);
      src.start(startAt);
      playheadRef.current = startAt + audioBuf.duration;
      sourcesRef.current.add(src);
      src.onended = () => {
        sourcesRef.current.delete(src);
        maybeFinishSpeaking();
      };
      if (stateRef.current === "thinking") setState("speaking");
    },
    [maybeFinishSpeaking, setState]
  );

  const ttsWorker = useCallback(async () => {
    if (ttsBusyRef.current) return;
    ttsBusyRef.current = true;
    while (ttsQueueRef.current.length) {
      const sentence = ttsQueueRef.current.shift()!;
      try {
        const res = await fetch("/api/v1/voice/say", {
          method: "POST",
          headers: { "Content-Type": "application/json", ...authHeader(token) },
          body: JSON.stringify({ text: sentence }),
        });
        if (res.ok) await schedulePlayback(await res.arrayBuffer());
      } catch {
        /* skip a failed sentence rather than break the turn */
      }
    }
    ttsBusyRef.current = false;
    maybeFinishSpeaking();
  }, [token, schedulePlayback, maybeFinishSpeaking]);

  const enqueueTTS = useCallback(
    (sentence: string) => {
      if (!sentence.trim()) return;
      ttsQueueRef.current.push(sentence.trim());
      void ttsWorker();
    },
    [ttsWorker]
  );

  const stopPlayback = useCallback(() => {
    sourcesRef.current.forEach((s) => {
      try {
        s.stop();
      } catch {
        /* ignore */
      }
    });
    sourcesRef.current.clear();
    ttsQueueRef.current = [];
    if (acRef.current) playheadRef.current = acRef.current.currentTime;
    if (chatAbortRef.current) chatAbortRef.current.abort();
  }, []);

  // ── Barge-in monitor (runs while speaking) ────────────────────────────────
  const startBargeMonitor = useCallback(() => {
    const analyser = analyserRef.current!;
    const buf = tdRef.current;
    let overMs = 0;
    let last = performance.now();
    const loop = () => {
      if (stateRef.current !== "speaking") {
        bargeRafRef.current = null;
        return;
      }
      const now = performance.now();
      const dt = now - last;
      last = now;
      overMs = rmsOf(analyser, buf) > BARGE_IN_RMS ? overMs + dt : 0;
      if (overMs >= BARGE_IN_MS) {
        stopPlayback();
        setState("listening");
        armLoopRef.current();
        bargeRafRef.current = null;
        return;
      }
      bargeRafRef.current = requestAnimationFrame(loop);
    };
    bargeRafRef.current = requestAnimationFrame(loop);
  }, [setState, stopPlayback]);

  // ── Conversation turn ─────────────────────────────────────────────────────
  const speakOnce = useCallback(
    async (text: string) => {
      // One-off line (e.g. a refusal) — synthesised and played, no chat round-trip.
      setState("speaking");
      streamDoneRef.current = true;
      enqueueTTS(text);
      startBargeMonitor();
    },
    [setState, enqueueTTS, startBargeMonitor]
  );

  const converse = useCallback(
    async (userText: string, isOwner: boolean) => {
      setState("thinking");
      streamDoneRef.current = false;
      const ctrl = new AbortController();
      chatAbortRef.current = ctrl;
      startBargeMonitor();
      let pending = "";
      try {
        const res = await fetch("/api/v1/chat/stream", {
          method: "POST",
          headers: { "Content-Type": "application/json", ...authHeader(token) },
          body: JSON.stringify({
            message: userText,
            session_id: sessionId,
            stream: true,
            is_voice: true, // concise 1–2 sentence spoken replies
            is_voice_owner: isOwner,
          }),
          signal: ctrl.signal,
        });
        if (!res.ok || !res.body) throw new Error(`HTTP ${res.status}`);
        const reader = res.body.getReader();
        const dec = new TextDecoder();
        let buf = "";
        while (true) {
          const { done, value } = await reader.read();
          if (done) break;
          buf += dec.decode(value, { stream: true });
          const lines = buf.split("\n");
          buf = lines.pop() ?? "";
          for (const line of lines) {
            if (!line.startsWith("data:")) continue;
            const raw = line.slice(5).trim();
            if (!raw) continue;
            try {
              const d = JSON.parse(raw);
              if (d.token !== undefined) {
                pending += d.token;
                let m: { sentence: string; rest: string } | null;
                while ((m = takeSentence(pending))) {
                  enqueueTTS(m.sentence);
                  pending = m.rest;
                }
              } else if (d.error) {
                pending += ` ${d.error}`;
              }
              // d.done and rich-content events are ignored on the voice path.
            } catch {
              /* ignore malformed SSE frame */
            }
          }
        }
      } catch (e: any) {
        if (e?.name !== "AbortError") enqueueTTS("Sorry, I hit a problem. Please try again.");
      } finally {
        streamDoneRef.current = true;
        if (pending.trim()) enqueueTTS(pending);
        // If the reply produced no audio at all, drop back to listening.
        if (!ttsBusyRef.current && ttsQueueRef.current.length === 0 && sourcesRef.current.size === 0) {
          setState("listening");
          armLoopRef.current();
        }
      }
    },
    [token, sessionId, setState, enqueueTTS, startBargeMonitor]
  );

  const onActivated = useCallback(async () => {
    try {
      let text = "";
      let isOwner = true;
      if (STT_MODE === "webspeech") {
        // Fast, NOT private — the browser vendor receives the audio. No local audio
        // is captured, so the sovereign owner-gate can't run on this path.
        text = await recognizeOnce();
      } else {
        const blob = await captureUtteranceBlob();
        if (!blob.size) {
          setState("listening");
          armLoopRef.current();
          return;
        }
        const fd = new FormData();
        fd.append("audio", blob, "utterance.webm");
        const res = await fetch("/api/v1/voice/transcribe", {
          method: "POST",
          headers: authHeader(token), // no Content-Type — browser sets the multipart boundary
          body: fd,
        });
        const data = await res.json();
        text = (data.text || "").trim();
        isOwner = data.is_owner !== false;
      }

      if (!text.trim()) {
        setState("listening");
        armLoopRef.current();
        return;
      }
      if (!isOwner) {
        // is_owner is false only when biometrics are ON and the speaker isn't the
        // enrolled owner (DEV_MODE always returns true) — refuse politely.
        await speakOnce("I'm sorry, I can only take voice commands from my owner.");
        return;
      }
      await converse(text, isOwner);
    } catch (e) {
      setState("listening");
      armLoopRef.current();
    }
  }, [token, captureUtteranceBlob, recognizeOnce, converse, speakOnce, setState]);

  // ── Arm / disarm the whole loop ───────────────────────────────────────────
  // Assigned every render so it always sees the latest onActivated/start* closures.
  armLoopRef.current = () => {
    if (!armedRef.current) return;
    setState("listening");
    if (ACTIVATION === "clap") startClap(onActivated);
    else startWakeWord(onActivated);
  };

  const start = useCallback(async () => {
    setError("");
    try {
      await ensureAudio();
    } catch {
      setError("Microphone permission denied.");
      return;
    }
    armedRef.current = true;
    armLoopRef.current();
  }, [ensureAudio]);

  const stop = useCallback(() => {
    armedRef.current = false;
    stopWatch();
    stopPlayback();
    if (bargeRafRef.current !== null) {
      cancelAnimationFrame(bargeRafRef.current);
      bargeRafRef.current = null;
    }
    streamDoneRef.current = true;
    setState("idle");
  }, [stopWatch, stopPlayback, setState]);

  const toggle = useCallback(() => {
    if (stateRef.current === "idle") void start();
    else stop();
  }, [start, stop]);

  // Cleanup on unmount.
  useEffect(() => {
    return () => {
      armedRef.current = false;
      stopWatch();
      stopPlayback();
      if (bargeRafRef.current !== null) cancelAnimationFrame(bargeRafRef.current);
      if (micRef.current) micRef.current.getTracks().forEach((t) => t.stop());
      if (acRef.current) void acRef.current.close();
    };
  }, [stopWatch, stopPlayback]);

  // ── UI (mirrors VoiceOrb's state visuals) ─────────────────────────────────
  const isActive = voiceState !== "idle";
  const stateLabel: Record<VoiceState, string> = {
    idle: "",
    listening: ACTIVATION === "clap" ? "Listening — double-clap" : `Listening — say "${WAKE_WORD}"`,
    thinking: "Thinking…",
    speaking: "Speaking",
  };
  const orbColor: Record<VoiceState, string> = {
    idle: "bg-neutral-800 border-neutral-700 text-neutral-400",
    listening: "bg-saffron-500/20 border-saffron-500 text-saffron-400",
    thinking: "bg-indigo-500/20 border-indigo-500 text-indigo-400",
    speaking: "bg-green-500/20 border-green-500 text-green-400",
  };
  const ringColor: Record<VoiceState, string> = {
    idle: "",
    listening: "bg-saffron-500/40",
    thinking: "bg-indigo-500/40",
    speaking: "bg-green-500/40",
  };

  return (
    <div className="relative flex flex-col items-center">
      {isActive && (
        <>
          <span className={clsx("absolute inset-0 rounded-full animate-pulse-ring", ringColor[voiceState])} />
          <span className={clsx("absolute inset-0 rounded-full animate-pulse-ring-d", ringColor[voiceState])} />
        </>
      )}

      <button
        onClick={toggle}
        title={isActive ? `IRA voice — ${stateLabel[voiceState]}` : "Start browser voice"}
        className={clsx(
          "relative z-10 w-8 h-8 rounded-full border flex items-center justify-center transition-all duration-300",
          orbColor[voiceState],
          isActive ? "shadow-lg" : "hover:border-neutral-500 hover:text-neutral-200"
        )}
      >
        {voiceState === "speaking" ? (
          <Volume2 className="w-3.5 h-3.5" />
        ) : voiceState === "thinking" ? (
          <Loader2 className="w-3.5 h-3.5 animate-spin" />
        ) : (
          <Mic className="w-3.5 h-3.5" />
        )}
      </button>

      {/* Wake word + Web Speech both send audio to the browser vendor — NOT private. */}
      {USES_CLOUD_SPEECH && (
        <span
          title="Web Speech sends audio to the browser vendor — not private. Use clap + whisper for a fully on-device path."
          className="absolute -top-3 right-0 z-50 text-[8px] px-1 rounded bg-red-900/80 border border-red-500/50 text-red-300 whitespace-nowrap"
        >
          not private
        </span>
      )}

      {stateLabel[voiceState] && (
        <span className="absolute -bottom-4 text-[10px] text-neutral-500 whitespace-nowrap">
          {stateLabel[voiceState]}
        </span>
      )}

      {error && (
        <div className="absolute top-10 right-0 z-50 bg-red-900/90 border border-red-500/50 text-red-300 text-xs rounded-lg px-3 py-2 w-48 shadow-xl">
          {error}
        </div>
      )}
    </div>
  );
}
