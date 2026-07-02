# SupraCloud IRA — UI Redesign Report

_Phase 4. Stack respected: Next.js 14 (App Router) + Tailwind CSS 3.4. **Zero new
dependencies added.** Verified with `tsc --noEmit`, `next build`, and live rendering
(desktop 1440×900 + mobile 390×844 screenshots under `assets/screenshots/`)._

## Old UI weaknesses

1. **Flat surfaces** — everything was `bg-neutral-900/950` boxes; no depth, glass, or
   brand atmosphere; the login screen looked like a generic admin panel.
2. **No design tokens** — colors/effects hardcoded per component; `globals.css` was 37 lines.
3. **Weak brand identity** — title in plain white; no local-first/privacy signal anywhere
   in the UI despite it being the product's core promise.
4. **Mobile overflow** — the mode-toggle chip row (Expert/Grok/Engineer/Think/DeepSearch/
   Architect) overflowed horizontally on small screens.
5. **Accessibility gaps** — icon-only buttons (send, stop, attach, copy, sidebar collapse)
   had no `aria-label`; no visible keyboard focus ring; login inputs had no `id`/`htmlFor`
   pairing or `autoComplete`; no `prefers-reduced-motion` handling.
6. **Sidebar always expanded** on phones, stealing a third of the viewport.
7. Page `<title>` was just "IRA" with a one-line description.

## New design system

Defined in `app/globals.css` (tokens + utilities) and `tailwind.config.ts` (shadows +
motion), dark-first:

- **Canvas**: near-black `#060608` with an **aurora wash** — two fixed radial gradients
  (saffron top-right, indigo bottom-left) that give every screen depth at zero JS cost.
- **Glass surface** (`.ira-glass`): `rgba(255,255,255,.035)` fill, hairline
  `rgba(255,255,255,.07)` border, 14px backdrop blur — used for header, sidebar, cards,
  assistant bubbles, input bar, modals.
- **Brand gradient text** (`.ira-gradient-text`): saffron → indigo, used for the product
  title and empty-state greeting.
- **Glow accents**: `shadow-glow-saffron` on primary CTAs and user bubbles;
  `.ira-orb-glow` halo on the brand orb.
- **Motion**: existing `fade-in`/`pulse-ring` kept; new `float-soft` (5s gentle hover for
  the orb); **all motion collapses under `prefers-reduced-motion`**.
- **Focus**: global `:focus-visible` saffron ring (keyboard-only, mouse clicks unaffected).
- Typography stays Inter (already loaded via `next/font`); hierarchy sharpened with
  tracking and the gradient display treatment instead of a new font download.

## Files changed

| File | Change |
| --- | --- |
| `app/globals.css` | design tokens, aurora canvas, glass + gradient + glow utilities, focus-visible ring, selection color, reduced-motion support, scrollbar polish |
| `tailwind.config.ts` | `shadow-panel`, `shadow-glow-saffron`, `float-soft` keyframes/animation |
| `app/layout.tsx` | real metadata (`SupraCloud IRA — Private, Local-First AI Assistant`, branded description), body switched to aurora canvas |
| `app/page.tsx` | login redesigned (glowing floating orb, gradient title, **"100% local & private" badge**, glass card, gradient CTA with glow, labeled inputs with `autoComplete`, `role="alert"` on errors, "built by Praveen Kamineti" footer); header now glass with a **🔒 Local privacy indicator** |
| `components/Sidebar.tsx` | glass surface, auto-collapse on <640px screens (post-hydration, no SSR mismatch), `aria-label`/`aria-expanded` on the collapse toggle |
| `components/ChatInterface.tsx` | empty state (glowing orb, gradient greeting, "Running locally — private by default" badge), user bubbles = saffron gradient + glow, assistant bubbles = glass, input bar = glass panel, Cost Guard modal = glass + `role="dialog"`, mode-toggle row **wraps on mobile**, `aria-label` on send/stop/attach/copy buttons, copy button reachable by keyboard (`focus-visible:opacity-100`) |

Deliberately **not** rebuilt: the SSE streaming logic, expert-mode panel, attachments,
voice components, and Zustand stores — all behavior untouched; this is a pure presentation
pass (no API or state changes), keeping the redesign safe and reviewable.

## Responsive behavior

- **Mobile (≤640px)**: sidebar auto-collapses to a 48px rail; mode toggles wrap into rows;
  keyboard-hint line hidden; login stacks cleanly at 390px (verified live, screenshot below).
- **Tablet/desktop**: header badges reveal progressively (`sm`/`md`/`lg`/`xl` steps,
  unchanged); chat column capped at `max-w-3xl`.

## Accessibility improvements

- Global keyboard focus ring (`:focus-visible`), including previously invisible hover-only
  controls (message copy button).
- `aria-label` on every icon-only button; `aria-expanded` on the sidebar toggle;
  `role="alert"` on the login error; `role="dialog" aria-modal` on the Cost Guard modal.
- Proper `<label htmlFor>` + `id` + `autoComplete` on login inputs (password managers now work).
- Decorative glyphs marked `aria-hidden`.
- `prefers-reduced-motion` disables all animation.
- Contrast: body text unchanged (neutral-100/400 on near-black passes AA); decorative
  micro-labels stay muted by design.

## How to run and verify

```bash
cd supracloud-jarvis/frontend
npm ci
npm run build        # passes — verified
npx tsc --noEmit     # passes — verified
npm run dev          # http://localhost:3000
```

## Screenshots

Real rendered captures (production build served with `next start`):

- `assets/screenshots/login-desktop.png` (1440×900)
- `assets/screenshots/login-mobile.png` (390×844)

The authenticated chat area needs the backend running; to capture it, start the stack
(`start-ira.ps1` or portable scripts), sign in, and screenshot the empty state + a
streamed conversation for the README.
