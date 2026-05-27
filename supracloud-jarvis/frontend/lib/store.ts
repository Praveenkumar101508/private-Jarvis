import { create } from "zustand";
import { persist, createJSONStorage } from "zustand/middleware";

// ── Types ──────────────────────────────────────────────────────────────────

export interface AgentBubble {
  name: string;
  label: string;
  emoji: string;
  content: string;
  done: boolean;
}

export interface AttachedFile {
  name: string;
  dataUrl: string;
  base64: string;
  mimeType: string;
  fileType: "image" | "document";
  rawBytes?: Uint8Array;
}

export interface Message {
  id: string;
  role: "user" | "assistant";
  content: string;
  agent?: string;
  latencyMs?: number;
  isStreaming?: boolean;
  isExpert?: boolean;
  expertAgents?: AgentBubble[];
  expertPanelOpen?: boolean;
  imageDataUrl?: string;
  generatedImageB64?: string;
  usedLiveX?: boolean;
  isEngineer?: boolean;
  isThink?: boolean;
  thinkingContent?: string;
  thinkingOpen?: boolean;
  deepSearchRounds?: number;
  attachedFileName?: string;
  isArchitect?: boolean;
  pendingApply?: boolean;
  videoUrl?: string;
  documentUrl?: string;
  audioUrl?: string;
}

// ── Auth Store (persisted in sessionStorage) ──────────────────────────────

interface AuthState {
  token: string;
  isAuthenticated: boolean;
  livekitToken: string;
  livekitUrl: string;
  setToken: (token: string) => void;
  setLivekitToken: (token: string, url: string) => void;
  logout: () => void;
}

export const useAuthStore = create<AuthState>()(
  persist(
    (set) => ({
      token: "",
      isAuthenticated: false,
      livekitToken: "",
      livekitUrl: "",
      setToken: (token) => set({ token, isAuthenticated: !!token }),
      setLivekitToken: (livekitToken, livekitUrl) => set({ livekitToken, livekitUrl }),
      logout: () => set({ token: "", isAuthenticated: false, livekitToken: "", livekitUrl: "" }),
    }),
    {
      name: "ira-auth",
      storage: createJSONStorage(() => sessionStorage),
      partialize: (state) => ({ token: state.token }),
    }
  )
);

// ── Chat Store (in-memory only, reset on refresh) ─────────────────────────

interface ChatState {
  messages: Message[];
  sessionId: string;
  isLoading: boolean;
  abortController: AbortController | null;
  attachedFile: AttachedFile | null;

  addMessage: (msg: Message) => void;
  updateMessage: (id: string, update: Partial<Message>) => void;
  appendToken: (id: string, token: string) => void;
  clearMessages: () => void;
  newSession: () => void;

  setLoading: (loading: boolean) => void;
  setAbortController: (ac: AbortController | null) => void;

  setAttachedFile: (file: AttachedFile | null) => void;
}

export const useChatStore = create<ChatState>()((set) => ({
  messages: [],
  sessionId: typeof crypto !== "undefined" ? crypto.randomUUID() : Math.random().toString(36).slice(2),
  isLoading: false,
  abortController: null,
  attachedFile: null,

  addMessage: (msg) =>
    set((state) => ({ messages: [...state.messages, msg] })),

  updateMessage: (id, update) =>
    set((state) => ({
      messages: state.messages.map((m) => (m.id === id ? { ...m, ...update } : m)),
    })),

  appendToken: (id, token) =>
    set((state) => ({
      messages: state.messages.map((m) =>
        m.id === id ? { ...m, content: m.content + token } : m
      ),
    })),

  clearMessages: () => set({ messages: [] }),

  newSession: () =>
    set({
      messages: [],
      sessionId: typeof crypto !== "undefined" ? crypto.randomUUID() : Math.random().toString(36).slice(2),
      isLoading: false,
    }),

  setLoading: (isLoading) => set({ isLoading }),

  setAbortController: (abortController) => set({ abortController }),

  setAttachedFile: (attachedFile) => set({ attachedFile }),
}));

// ── UI Store ──────────────────────────────────────────────────────────────

type AppMode = "assistant" | "tutor" | "bodyguard";

interface UIState {
  mode: AppMode;
  sidebarOpen: boolean;
  expertMode: boolean;
  engineerMode: boolean;
  thinkMode: boolean;
  deepSearch: boolean;
  grokMode: boolean;
  setMode: (mode: AppMode) => void;
  setSidebarOpen: (open: boolean) => void;
  toggleExpertMode: () => void;
  toggleEngineerMode: () => void;
  toggleThinkMode: () => void;
  toggleDeepSearch: () => void;
  toggleGrokMode: () => void;
}

export const useUIStore = create<UIState>()((set) => ({
  mode: "assistant",
  sidebarOpen: false,
  expertMode: false,
  engineerMode: false,
  thinkMode: false,
  deepSearch: false,
  grokMode: false,
  setMode: (mode) => set({ mode }),
  setSidebarOpen: (sidebarOpen) => set({ sidebarOpen }),
  toggleExpertMode: () => set((s) => ({ expertMode: !s.expertMode })),
  toggleEngineerMode: () => set((s) => ({ engineerMode: !s.engineerMode })),
  toggleThinkMode: () => set((s) => ({ thinkMode: !s.thinkMode })),
  toggleDeepSearch: () => set((s) => ({ deepSearch: !s.deepSearch })),
  toggleGrokMode: () => set((s) => ({ grokMode: !s.grokMode })),
}));
