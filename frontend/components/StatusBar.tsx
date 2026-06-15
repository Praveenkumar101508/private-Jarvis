"use client";

import { useEffect, useState } from "react";
import clsx from "clsx";

interface ServiceStatus {
  status: "ok" | "degraded" | "down";
  latency_ms: number;
}

interface Health {
  status: string;
  version: string;
  services: Record<string, ServiceStatus>;
}

export default function StatusBar({ token }: { token: string }) {
  const [health, setHealth] = useState<Health | null>(null);

  useEffect(() => {
    const check = async () => {
      try {
        const res = await fetch("/health", {
          headers: { Authorization: `Bearer ${token}` },
        });
        if (res.ok) setHealth(await res.json());
      } catch {
        setHealth(null);
      }
    };
    check();
    const id = setInterval(check, 30_000);
    return () => clearInterval(id);
  }, [token]);

  if (!health) return null;

  const ok = health.status === "ok";

  return (
    <div
      className={clsx(
        "hidden sm:flex items-center gap-1.5 text-xs px-2.5 py-1 rounded-full border",
        ok
          ? "bg-green-500/10 border-green-500/25 text-green-400"
          : "bg-yellow-500/10 border-yellow-500/25 text-yellow-400"
      )}
    >
      <span
        className={clsx(
          "w-1.5 h-1.5 rounded-full",
          ok ? "bg-green-400" : "bg-yellow-400"
        )}
      />
      <span>
        {ok ? "All systems online" : "Degraded"} · v{health.version}
      </span>
    </div>
  );
}
