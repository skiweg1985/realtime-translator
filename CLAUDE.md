# Translate Live

Real-time translation web app: one speaker, many listeners, audio and text. React + Vite frontend in `frontend/`, FastAPI backend in `backend/`, HAProxy for HTTPS, everything in `compose.yaml`.

## Design rules

The full UX briefs live in `docs/ux-guidelines.md`. Read them before touching the frontend. The short version:

- Touch-first. Design the iPhone one-handed interaction first, then widen for desktop. Every control at least 44x44 CSS px, frequent ones larger, in the lower half of the screen.
- Purpose-built, not generic. No marketing hero inside the app, no orb, no glassmorphism, no gradient blobs, no chat bubbles, no card around every section. Typography and the live translation carry the interface.
- One identity motif: the translation line between source and target language. It shows session state and reacts to real audio level. Do not add further decorative effects.
- Listener modes `Ton + Text`, `Ton`, `Text` switch with one tap. Text mode has large touch-friendly size options and a focus view with almost no UI.
- Progressive disclosure through bottom sheets, never tiny dropdowns or icon rows.
- All colours and fonts come from tokens in `frontend/src/tokens.css`. Light and dark stay monochrome.
- Respect `prefers-reduced-motion`, safe areas, `dvh`, landscape, and 200 % browser zoom.
- Copy is short, functional German. No AI-style phrases.

## Development

`npm run dev` in `frontend/` proxies `/api` and the WebSocket to the running Compose stack on port 8443 (see README). The backend compares the Origin host with the Host header, so the proxy must not rewrite the host.
