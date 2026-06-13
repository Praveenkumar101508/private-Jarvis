"use client";

import { useEffect } from "react";

/**
 * Registers the PWA service worker (public/sw.js) so IRA is installable
 * ("Add to Home Screen") and the app shell loads offline. Production only —
 * a dev SW fights Next's HMR and caches stale chunks.
 */
export default function PWARegister() {
  useEffect(() => {
    if (
      typeof navigator !== "undefined" &&
      "serviceWorker" in navigator &&
      process.env.NODE_ENV === "production"
    ) {
      navigator.serviceWorker.register("/sw.js").catch(() => {
        /* SW registration is best-effort; the app works without it */
      });
    }
  }, []);
  return null;
}
