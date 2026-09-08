import React, { useEffect, useRef, useState } from "react";
import { flushSync } from "react-dom";
import { createRoot } from "react-dom/client";
import {
  Mic,
  MicOff,
  Headphones,
  Captions as CaptionsIcon,
  BookOpen,
  Check,
  Square,
  Volume2,
  VolumeX,
  X,
  ChevronDown,
  ChevronUp,
  ChevronRight,
  Link,
  Share,
  Loader2,
  AlertCircle,
  Info,
  ALargeSmall,
  Maximize2,
  LogOut,
  Settings2,
  Camera,
} from "lucide-react";
import { QRCodeSVG } from "qrcode.react";
import "@fontsource-variable/inter/opsz.css";
import "./style.css";
import { detectLang, translate, type Key, type Lang } from "./i18n";

const languages: Record<string, string> = {
  de: "Deutsch",
  en: "English",
  fr: "Français",
  es: "Español",
  it: "Italiano",
  pt: "Português",
  nl: "Nederlands",
  pl: "Polski",
  uk: "Українська",
  tr: "Türkçe",
  ar: "العربية",
  ja: "日本語",
  zh: "中文",
};
const languageOptions = Object.entries(languages) as [string, string][];
type Status = "idle" | "connecting" | "live" | "waiting" | "ended" | "draining" | "error";
type Role = "home" | "speaker" | "listener";
type Mode = "both" | "audio" | "text";
type Size = "normal" | "large" | "xl";
type Theme = "system" | "light" | "dark";
type SheetKind = "language" | "share" | "textSize" | "device" | "audio" | "settings" | "join" | null;
const sizes: Record<Size, { label: Key; short: Key; scale: number; preview: number }> = {
  normal: { label: "sizeNormal", short: "sizeNormal", scale: 1, preview: 17 },
  large: { label: "sizeLarge", short: "sizeLarge", scale: 1.25, preview: 22 },
  xl: { label: "sizeXl", short: "sizeXlShort", scale: 1.6, preview: 28 },
};
const modes: { key: Mode; label: Key; icon: React.ReactNode }[] = [
  { key: "both", label: "modeBoth", icon: <CaptionsIcon size={20} /> },
  { key: "audio", label: "modeAudio", icon: <Headphones size={20} /> },
  { key: "text", label: "modeText", icon: <BookOpen size={20} /> },
];
const themes: { key: Theme; label: Key }[] = [
  { key: "system", label: "themeSystem" },
  { key: "light", label: "themeLight" },
  { key: "dark", label: "themeDark" },
];
const LEVELS = 48;

function stored(key: string) {
  try {
    return localStorage.getItem(key);
  } catch {
    return null;
  }
}
function store(key: string, value: string) {
  try {
    localStorage.setItem(key, value);
  } catch {}
}

/* Den laufenden Text in Verlauf und aktuellen Satz teilen. */
function splitCaption(text: string) {
  const t = text.trim();
  if (!t) return { history: "", current: "" };
  const boundary = /[.!?…。！？]["“”»)]*\s+/g;
  let cut = 0;
  for (let m = boundary.exec(t); m; m = boundary.exec(t)) cut = m.index + m[0].length;
  if (cut === 0 && t.length > 220) {
    const i = t.lastIndexOf(" ", t.length - 140);
    if (i > 0) cut = i + 1;
  }
  return { history: t.slice(0, cut).trimEnd(), current: t.slice(cut) };
}

/* Eine Raum-ID aus einem eingefügten Link oder Text holen. */
function roomFromText(value: string) {
  const match = value.match(/room=([A-Za-z0-9_-]{8,})/) || value.trim().match(/^([A-Za-z0-9_-]{16,})$/);
  return match ? match[1] : "";
}

function reducedMotion() {
  return window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}

/* Pegelanzeige aus echten Audiodaten: die letzten Werte als Balken über einer Grundlinie. */
function LevelMeter({
  levels,
  active,
  className = "",
}: {
  levels: React.MutableRefObject<Float32Array>;
  active: boolean;
  className?: string;
}) {
  const ref = useRef<HTMLCanvasElement>(null);
  useEffect(() => {
    const canvas = ref.current;
    const ctx = canvas?.getContext("2d");
    if (!canvas || !ctx) return;
    let frame = 0;
    const draw = () => {
      const dpr = window.devicePixelRatio || 1;
      const w = canvas.clientWidth,
        h = canvas.clientHeight;
      if (canvas.width !== Math.round(w * dpr) || canvas.height !== Math.round(h * dpr)) {
        canvas.width = Math.round(w * dpr);
        canvas.height = Math.round(h * dpr);
      }
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      ctx.clearRect(0, 0, w, h);
      ctx.fillStyle = getComputedStyle(canvas).color;
      const data = levels.current,
        n = data.length,
        gap = 3,
        bw = Math.max(2, (w - gap * (n - 1)) / n);
      ctx.globalAlpha = 0.22;
      ctx.fillRect(0, Math.round(h / 2), w, 1);
      if (!active) return;
      for (let i = 0; i < n; i++) {
        data[i] = Math.max(0, data[i] * 0.965);
        const bh = Math.min(h, data[i] * h);
        if (bh < 1.5) continue;
        ctx.globalAlpha = 0.3 + 0.7 * ((i + 1) / n);
        ctx.fillRect(i * (bw + gap), (h - bh) / 2, bw, bh);
      }
      frame = requestAnimationFrame(draw);
    };
    draw();
    return () => cancelAnimationFrame(frame);
  }, [active, levels]);
  return <canvas ref={ref} className={"meter " + className} aria-hidden="true" />;
}

/* QR-Scanner: Kamera-Vorschau, erkannt über BarcodeDetector oder jsQR als Fallback. */
function Scanner({
  onResult,
  onError,
}: {
  onResult: (text: string) => void;
  onError: () => void;
}) {
  const video = useRef<HTMLVideoElement>(null);
  useEffect(() => {
    let stream: MediaStream | null = null,
      stopped = false,
      timer = 0;
    const canvas = document.createElement("canvas");
    (async () => {
      try {
        stream = await navigator.mediaDevices.getUserMedia({
          video: { facingMode: { ideal: "environment" } },
          audio: false,
        });
      } catch {
        onError();
        return;
      }
      const v = video.current;
      if (stopped || !v) {
        stream.getTracks().forEach((track) => track.stop());
        return;
      }
      v.srcObject = stream;
      await v.play().catch(() => {});
      const Detector = (window as any).BarcodeDetector;
      let detector: any = null;
      if (Detector) {
        try {
          detector = new Detector({ formats: ["qr_code"] });
        } catch {
          detector = null;
        }
      }
      const jsQR = detector ? null : (await import("jsqr")).default;
      const scan = async () => {
        if (stopped) return;
        if (v.readyState >= 2 && v.videoWidth) {
          try {
            if (detector) {
              const codes = await detector.detect(v);
              if (codes[0]?.rawValue) {
                onResult(codes[0].rawValue);
                return;
              }
            } else if (jsQR) {
              const w = Math.min(640, v.videoWidth),
                h = Math.round((w * v.videoHeight) / v.videoWidth);
              canvas.width = w;
              canvas.height = h;
              const ctx = canvas.getContext("2d", { willReadFrequently: true })!;
              ctx.drawImage(v, 0, 0, w, h);
              const image = ctx.getImageData(0, 0, w, h);
              const found = jsQR(image.data, w, h, { inversionAttempts: "dontInvert" });
              if (found?.data) {
                onResult(found.data);
                return;
              }
            }
          } catch {}
        }
        timer = window.setTimeout(scan, 150);
      };
      scan();
    })();
    return () => {
      stopped = true;
      clearTimeout(timer);
      stream?.getTracks().forEach((track) => track.stop());
    };
  }, []);
  return <video ref={video} className="scanner" playsInline muted autoPlay />;
}

/* Untertitel: Verlauf oben, aktueller Satz groß und unten verankert. */
function Captions({
  label,
  lang,
  text,
  placeholder,
  endRef,
}: {
  label: string;
  lang: string;
  text: string;
  placeholder: string;
  endRef: React.RefObject<HTMLDivElement | null>;
}) {
  const { history, current } = splitCaption(text);
  return (
    <section className="captions" aria-label={label}>
      <div className="captions-label">
        {label} <span>· {lang}</span>
      </div>
      <div className="caption">
        {history && <p className="caption-history">{history}</p>}
        <p className="caption-current" aria-live="polite">
          {current || <span className="placeholder">{placeholder}</span>}
        </p>
        <div ref={endRef} />
      </div>
    </section>
  );
}

/* Bottom Sheet auf dem Telefon, Dialog auf großen Screens. Escape, Tipp daneben und Wischen schließen. */
function Sheet({
  title,
  closeLabel,
  onClose,
  children,
}: {
  title: string;
  closeLabel: string;
  onClose: () => void;
  children: React.ReactNode;
}) {
  const ref = useRef<HTMLElement>(null);
  const [drag, setDrag] = useState(0);
  const start = useRef<number | null>(null),
    now = useRef(0);
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [onClose]);
  function onTouchStart(e: React.TouchEvent<HTMLElement>) {
    if (ref.current && ref.current.scrollTop > 0) return;
    start.current = e.touches[0].clientY;
    now.current = 0;
  }
  function onTouchMove(e: React.TouchEvent<HTMLElement>) {
    if (start.current === null) return;
    const dy = Math.max(0, e.touches[0].clientY - start.current);
    now.current = dy;
    setDrag(dy);
  }
  function onTouchEnd() {
    if (start.current === null) return;
    start.current = null;
    if (now.current > 80) onClose();
    else setDrag(0);
  }
  return (
    <div className="sheet-backdrop" onClick={onClose}>
      <section
        ref={ref}
        className={"sheet " + (drag > 0 ? "is-dragging" : "")}
        role="dialog"
        aria-modal="true"
        aria-label={title}
        style={drag > 0 ? { transform: `translateY(${drag}px)` } : undefined}
        onClick={(e) => e.stopPropagation()}
        onTouchStart={onTouchStart}
        onTouchMove={onTouchMove}
        onTouchEnd={onTouchEnd}
        onTouchCancel={onTouchEnd}
      >
        <div className="grabber" aria-hidden="true" />
        <div className="sheet-head">
          <h2>{title}</h2>
          <button className="close" onClick={onClose} aria-label={closeLabel}>
            <X size={22} />
          </button>
        </div>
        {children}
      </section>
    </div>
  );
}

function Option({
  label,
  detail,
  preview,
  selected,
  onSelect,
}: {
  label: string;
  detail?: string;
  preview?: React.ReactNode;
  selected: boolean;
  onSelect: () => void;
}) {
  return (
    <button className="option" role="radio" aria-checked={selected} onClick={onSelect}>
      <span className="option-main">
        {preview}
        <span>
          {label}
          {detail && <small>{detail}</small>}
        </span>
      </span>
      {selected && <Check size={20} aria-hidden="true" />}
    </button>
  );
}

function Segmented<T extends string>({
  value,
  options,
  onChange,
  label,
}: {
  value: T;
  options: { key: T; label: string; icon?: React.ReactNode }[];
  onChange: (value: T) => void;
  label: string;
}) {
  return (
    <div className="segmented" role="radiogroup" aria-label={label}>
      {options.map((o) => (
        <button key={o.key} role="radio" aria-checked={value === o.key} onClick={() => onChange(o.key)}>
          {o.icon}
          {o.label}
        </button>
      ))}
    </div>
  );
}

function App() {
  const params = new URLSearchParams(location.hash.slice(1));
  const [room, setRoom] = useState(params.get("room") || "");
  const [owner, setOwner] = useState(
    sessionStorage.getItem("owner:" + room) || "",
  );
  const [role, setRole] = useState<Role>(room ? (owner ? "speaker" : "listener") : "home");
  const listener = role === "listener";
  const [ui, setUi] = useState<Lang>(() => {
    const saved = stored("translate:ui");
    return saved === "de" || saved === "en" ? saved : detectLang();
  });
  const [theme, setTheme] = useState<Theme>(() => {
    const saved = stored("translate:theme");
    return saved === "light" || saved === "dark" ? saved : "system";
  });
  const [source, setSource] = useState("de"),
    [language, setLanguage] = useState("en");
  const selectedLanguage = useRef("en"), subscription = useRef(0);
  const audioNodes = useRef(new Set<AudioBufferSourceNode>());
  const [status, setStatus] = useState<Status>("idle");
  const [original, setOriginal] = useState(""),
    [text, setText] = useState("");
  const [error, setError] = useState(""),
    [notice, setNotice] = useState("");
  const [count, setCount] = useState(0),
    [copied, setCopied] = useState(false);
  const [muted, setMuted] = useState(false),
    [micMuted, setMicMuted] = useState(false),
    [elapsed, setElapsed] = useState(0);
  const [audioInfo, setAudioInfo] = useState({ chunks: 0, peak: 0, state: "nicht gestartet" });
  const [toneResult, setToneResult] = useState("");
  const [transcription, setTranscription] = useState("loading");
  const [devices, setDevices] = useState<MediaDeviceInfo[]>([]),
    [device, setDevice] = useState("");
  const [mode, setMode] = useState<Mode>("both");
  const [size, setSize] = useState<Size>(() => {
    const saved = stored("translate:size");
    return saved && saved in sizes ? (saved as Size) : "normal";
  });
  const [focus, setFocus] = useState(false);
  const [sheet, setSheet] = useState<SheetKind>(null);
  const [langTab, setLangTab] = useState<"source" | "target">("target");
  const [code, setCode] = useState("");
  const [joinCode, setJoinCode] = useState(""),
    [joinText, setJoinText] = useState(""),
    [joinError, setJoinError] = useState(""),
    [joining, setJoining] = useState(false),
    [scanning, setScanning] = useState(false),
    [linkField, setLinkField] = useState(false);
  const socket = useRef<WebSocket | null>(null),
    context = useRef<AudioContext | null>(null),
    stream = useRef<MediaStream | null>(null);
  const capture = useRef<AudioWorkletNode | null>(null),
    nextAudio = useRef(0),
    audioGain = useRef<GainNode | null>(null);
  const route = useRef<HTMLDivElement>(null),
    levels = useRef(new Float32Array(LEVELS)),
    running = useRef(false),
    micOff = useRef(false),
    wake = useRef<any>(null);
  const transcriptEnd = useRef<HTMLDivElement>(null);
  const t = (key: Key, vars?: Record<string, string>) => translate(ui, key, vars);
  useEffect(() => {
    fetch("/api/health")
      .then((r) => r.json())
      .then((x) => setTranscription(x.transcription));
    if (room)
      fetch("/api/rooms/" + room)
        .then(async (r) => {
          const x = await r.json();
          if (!r.ok) throw Error(x.detail);
          if (subscription.current === 0) {
            setLanguage(x.language);
            selectedLanguage.current = x.language;
          }
          setSource(x.source);
          if (x.code) setCode(x.code);
        })
        .catch((e) => setError(e.message));
  }, []);
  useEffect(() => {
    const timer = setInterval(
      () =>
        fetch("/api/health")
          .then((r) => r.json())
          .then((x) => setTranscription(x.transcription))
          .catch(() => {}),
      10000,
    );
    return () => clearInterval(timer);
  }, []);
  useEffect(() => {
    if (status !== "live") return;
    const t = setInterval(() => setElapsed((x) => x + 1), 1000);
    return () => clearInterval(t);
  }, [status]);
  useEffect(() => {
    const box = transcriptEnd.current?.parentElement;
    if (box && (text || original)) box.scrollTop = box.scrollHeight;
  }, [text, original, mode, size, focus]);
  useEffect(() => {
    if (!focus || sheet) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setFocus(false);
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [focus, sheet]);
  useEffect(() => store("translate:size", size), [size]);
  useEffect(() => {
    store("translate:ui", ui);
    document.documentElement.lang = ui;
  }, [ui]);
  useEffect(() => {
    store("translate:theme", theme);
    const root = document.documentElement;
    if (theme === "system") root.removeAttribute("data-theme");
    else root.setAttribute("data-theme", theme);
    // Die Browserleiste folgt der gewählten Darstellung.
    document.querySelectorAll<HTMLMetaElement>('meta[name="theme-color"]').forEach((meta) => {
      const light = meta.media.includes("light");
      const forced = theme === "light" ? "#f6f6f6" : theme === "dark" ? "#111111" : "";
      meta.content = forced || (light ? "#f6f6f6" : "#111111");
    });
  }, [theme]);
  useEffect(
    () => () => {
      socket.current?.close();
      stopMic();
      context.current?.close();
    },
    [],
  );
  const active = ["connecting", "live", "draining"].includes(status);
  const busy = status === "connecting" || status === "draining";
  const joined = status !== "idle" && status !== "ended";
  const session = status !== "idle";
  const link = location.origin + "/#room=" + room;
  const canShare =
    typeof navigator !== "undefined" && typeof navigator.share === "function";
  const clock =
    Math.floor(elapsed / 60) + ":" + String(elapsed % 60).padStart(2, "0");
  const languagesLocked = !listener && !!room;
  function pushLevel(value: number) {
    const data = levels.current;
    data.copyWithin(0, 1);
    data[data.length - 1] = value;
    route.current?.style.setProperty("--energy", String(value));
  }
  function describeError(e: unknown) {
    const name = e instanceof DOMException ? e.name : "";
    if (name === "NotAllowedError" || name === "PermissionDeniedError") return t("errMicDenied");
    if (name === "NotFoundError" || name === "OverconstrainedError") return t("errMicNotFound");
    if (name === "NotReadableError") return t("errMicBusy");
    return e instanceof Error && e.message ? e.message : t("errMicGeneric");
  }
  function stopMic() {
    running.current = false;
    capture.current?.disconnect();
    capture.current = null;
    stream.current?.getTracks().forEach((t) => t.stop());
    stream.current = null;
    wake.current?.release().catch(() => {});
    wake.current = null;
  }
  async function setupAudio() {
    if (!context.current || context.current.state === "closed") {
      context.current = new AudioContext();
      context.current.onstatechange = () => setAudioInfo(info => ({...info, state: context.current?.state || "closed"}));
      audioGain.current = context.current.createGain();
      audioGain.current.connect(context.current.destination);
      audioGain.current.gain.value = muted ? 0 : 1;
      nextAudio.current = 0;
    }
    await context.current.resume();
  }
  function play(delta: string) {
    const ctx = context.current;
    if (!ctx || !audioGain.current) return;
    const bin = atob(delta),
      bytes = new Uint8Array(bin.length);
    for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
    const pcm = new DataView(bytes.buffer),
      buffer = ctx.createBuffer(1, bytes.length / 2, 24000),
      samples = buffer.getChannelData(0);
    for (let i = 0; i < samples.length; i++)
      samples[i] = pcm.getInt16(i * 2, true) / 32768;
    let peak = 0;
    for (const sample of samples) peak = Math.max(peak, Math.abs(sample));
    setAudioInfo(info => ({chunks: info.chunks + 1, peak: Math.round(peak * 100), state: ctx.state}));
    const node = ctx.createBufferSource();
    node.buffer = buffer;
    node.connect(audioGain.current);
    audioNodes.current.add(node);
    node.onended = () => { audioNodes.current.delete(node); node.disconnect(); };
    nextAudio.current = Math.max(ctx.currentTime + 0.04, nextAudio.current);
    if (nextAudio.current - ctx.currentTime > 3) {
      setNotice(t("noticeBehind"));
      socket.current?.close();
      return;
    }
    node.start(nextAudio.current);
    nextAudio.current += buffer.duration;
    pushLevel(Math.min(1, peak * 1.6));
  }
  function clearPlayback() {
    for (const node of audioNodes.current) {
      try { node.stop(); } catch {}
      node.disconnect();
    }
    audioNodes.current.clear();
    nextAudio.current = 0;
    setAudioInfo(info => ({...info, chunks: 0, peak: 0}));
  }
  function chooseLanguage(value: string) {
    selectedLanguage.current = value;
    setLanguage(value);
    setText("");
    setError("");
    setNotice("");
    clearPlayback();
    subscription.current += 1;
    if (listener && socket.current?.readyState === WebSocket.OPEN) {
      setStatus("connecting");
      socket.current.send(JSON.stringify({type: "subscribe", language: value, subscription: subscription.current}));
    }
  }
  async function start() {
    setError("");
    setNotice("");
    setElapsed(0);
    setStatus("connecting");
    if (listener) {
      const old = socket.current;
      socket.current = null;
      old?.close();
      clearPlayback();
      subscription.current += 1;
      selectedLanguage.current = language;
    }
    try {
      await setupAudio(); // Must start inside the user's gesture on iOS.
      let id = room,
        secret = owner;
      if (!listener) {
        if (!navigator.mediaDevices?.getUserMedia) throw Error(t("errHttps"));
        stream.current = await navigator.mediaDevices.getUserMedia({
          audio: {
            deviceId: device ? { exact: device } : undefined,
            echoCancellation: true,
            noiseSuppression: true,
            autoGainControl: true,
            channelCount: 1,
          },
        });
        setDevices(
          (await navigator.mediaDevices.enumerateDevices()).filter(
            (d) => d.kind === "audioinput",
          ),
        );
        await context.current!.audioWorklet.addModule("/capture.js");
        if (!id) {
          const response = await fetch("/api/rooms", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ source, language }),
          });
          const data = await response.json();
          if (!response.ok) throw Error(data.detail || t("errRoom"));
          id = data.id;
          secret = data.owner;
          setCode(data.code || "");
          sessionStorage.setItem("owner:" + id, secret);
          setRoom(id);
          setOwner(secret);
          history.replaceState(null, "", "#room=" + id);
        }
      }
      if ("wakeLock" in navigator)
        try {
          wake.current = await (navigator as any).wakeLock.request("screen");
        } catch {}
      const ws = new WebSocket(
        (location.protocol === "https:" ? "wss://" : "ws://") +
          location.host +
          "/api/rooms/" +
          id +
          "/ws",
      );
      socket.current = ws;
      ws.onopen = () =>
        ws.send(
          JSON.stringify(
            listener
              ? { role: "listener", language: selectedLanguage.current, subscription: subscription.current }
              : { role: "speaker", owner: secret },
          ),
        );
      ws.onmessage = (message) => {
        if (socket.current !== ws) return;
        const event = JSON.parse(message.data);
        if (event.type === "subscription_rejected") {
          if (event.subscription !== subscription.current) return;
          subscription.current = event.active_subscription;
          selectedLanguage.current = event.language || language;
          setLanguage(selectedLanguage.current);
          setText(event.text || "");
          setStatus(event.status || "waiting");
          setError(event.message);
          return;
        }
        if (listener && event.language && (event.language !== selectedLanguage.current || event.subscription !== subscription.current)) return;
        if (event.type === "snapshot") {
          setText(event.text);
          setOriginal(event.original);
          setStatus(event.status);
        }
        if (event.type === "status") {
          setStatus(event.status);
          if (event.status === "live" && !listener && !running.current) {
            running.current = true;
            const ctx = context.current!,
              node = new AudioWorkletNode(ctx, "capture");
            capture.current = node;
            const input = ctx.createMediaStreamSource(stream.current!);
            input.connect(node);
            const silent = ctx.createGain();
            silent.gain.value = 0;
            node.connect(silent);
            silent.connect(ctx.destination);
            node.port.onmessage = (e) => {
              if (!running.current || ws.readyState !== WebSocket.OPEN) return;
              if (micOff.current) {
                pushLevel(0);
                return;
              }
              if (ws.bufferedAmount > 48000) {
                setError(t("errSlow"));
                stopMic();
                ws.close();
                return;
              }
              ws.send(e.data);
              const samples = new Int16Array(e.data);
              let energy = 0;
              for (const value of samples) energy += value * value;
              pushLevel(Math.min(1, Math.sqrt(energy / samples.length) / 5000));
            };
          }
          if (event.status === "ended") stopMic();
        }
        if (event.type === "translation") setText(event.text);
        if (event.type === "original") setOriginal(event.text);
        if (event.type === "listeners") setCount(event.count);
        if (event.type === "audio" && listener) play(event.delta);
        if (event.type === "error") setError(event.message);
        if (event.type === "notice") setNotice(event.message);
      };
      ws.onerror = () => {
        if (socket.current !== ws) return;
        setError(t("errConnection"));
      };
      ws.onclose = () => {
        if (socket.current !== ws) return;
        stopMic();
        setStatus((s) => (s === "idle" ? "idle" : "ended"));
      };
    } catch (e) {
      stopMic();
      setStatus("idle");
      setError(describeError(e));
    }
  }
  function stop() {
    stopMic();
    if (listener) {
      clearPlayback();
      socket.current?.close();
      context.current?.close();
      context.current = null;
    } else {
      setStatus("draining");
      socket.current?.send("stop");
    }
  }
  /* Mikrofon stumm: Track aus und nichts mehr senden, Sitzung bleibt offen. */
  function setMic(on: boolean) {
    micOff.current = !on;
    setMicMuted(!on);
    stream.current?.getAudioTracks().forEach((track) => (track.enabled = on));
    if (!on) pushLevel(0);
  }
  async function copy() {
    try {
      await navigator.clipboard.writeText(link);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      setNotice(t("noticeCopy"));
    }
  }
  async function shareLink() {
    try {
      await navigator.share({ title: "Translate Live", text: t("shareText", { code }), url: link });
    } catch {
      /* Abgebrochen oder nicht erlaubt: kein Fehler für den Nutzer. */
    }
  }
  async function testTone() {
    try {
      await setupAudio();
      const ctx = context.current!;
      const tone = ctx.createOscillator(), gain = ctx.createGain();
      tone.frequency.value = 660;
      gain.gain.setValueAtTime(0.08, ctx.currentTime);
      gain.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + 0.4);
      tone.connect(gain); gain.connect(ctx.destination);
      tone.start(); tone.stop(ctx.currentTime + 0.4);
      tone.onended = () => { tone.disconnect(); gain.disconnect(); };
      setToneResult(t("tonePlayed") + " · " + ctx.state);
    } catch { setToneResult(t("toneBlocked")); }
  }
  function setAudio(on: boolean) {
    setMuted(!on);
    if (audioGain.current) audioGain.current.gain.value = on ? 1 : 0;
  }
  /* Moduswechsel mit View Transition, wenn der Browser sie kann. */
  function switchMode(next: Mode) {
    if (next === mode) return;
    const apply = () =>
      flushSync(() => {
        setMode(next);
        setAudio(next !== "text");
        if (next !== "text") setFocus(false);
      });
    const doc = document as Document & { startViewTransition?: (cb: () => void) => void };
    if (doc.startViewTransition && !reducedMotion()) doc.startViewTransition(apply);
    else apply();
  }
  function openLanguages(tab: "source" | "target") {
    setLangTab(tab);
    setSheet("language");
  }
  function pickLanguage(code: string) {
    if (listener) chooseLanguage(code);
    else if (langTab === "source") setSource(code);
    else setLanguage(code);
    setSheet(null);
  }
  function openRoom(id: string) {
    location.assign("/#room=" + id);
    location.reload();
  }
  function joinLink(value: string) {
    const id = roomFromText(value);
    if (!id) {
      setJoinError(t("joinInvalid"));
      return;
    }
    openRoom(id);
  }
  async function joinByCode(value: string) {
    setJoining(true);
    setJoinError("");
    try {
      const r = await fetch("/api/rooms/by-code/" + encodeURIComponent(value));
      const x = await r.json();
      if (!r.ok) throw Error(x.detail || t("joinCodeInvalid"));
      openRoom(x.id);
    } catch (e) {
      setJoinError(e instanceof Error && e.message ? e.message : t("joinCodeInvalid"));
      setJoining(false);
    }
  }
  function closeJoin() {
    setSheet(null);
    setScanning(false);
    setJoinError("");
  }
  const statusLabel: Record<Status, string> = {
    idle: listener ? t("statusIdleListener") : t("statusIdleSpeaker"),
    connecting: t("statusConnecting"),
    live: listener ? t("statusLiveListener") : micMuted ? t("statusMuted") : t("statusLiveSpeaker"),
    waiting: t("statusWaiting"),
    ended: t("statusEnded"),
    draining: t("statusDraining"),
    error: t("statusError"),
  };
  const stateLabel: Record<Status, string> = {
    idle: t("stateIdle"),
    connecting: t("stateConnecting"),
    live: t("stateLive"),
    waiting: t("stateWaiting"),
    ended: t("stateEnded"),
    draining: t("stateDraining"),
    error: t("stateError"),
  };
  const deviceLabel =
    devices.find((d) => d.deviceId === device)?.label || t("micDefault");
  const showText = listener ? mode !== "audio" : true;
  const showAudio = listener && mode !== "text";
  const stateView = (
    <div className={"state " + status} role="status">
      <span className="state-dot" aria-hidden="true" />
      <span>{stateLabel[status]}</span>
      {status === "live" && <span className="timer">{clock}</span>}
    </div>
  );
  const settingsButton = (
    <button className="iconbtn" onClick={() => setSheet("settings")} aria-label={t("settings")}>
      <Settings2 size={22} />
    </button>
  );
  const alerts = (
    <>
      {error && (
        <div className="alert" role="alert">
          <AlertCircle size={18} aria-hidden="true" />
          <span>{error}</span>
          <button className="dismiss" onClick={() => setError("")} aria-label={t("dismissError")}>
            <X size={18} />
          </button>
        </div>
      )}
      {notice && (
        <div className="notice">
          <Info size={18} aria-hidden="true" />
          <span>{notice}</span>
          <button className="dismiss" onClick={() => setNotice("")} aria-label={t("dismissNotice")}>
            <X size={18} />
          </button>
        </div>
      )}
    </>
  );
  const sourceLang = (
    <>
      <small>{t("spoken")}</small>
      <span className="lang-value">
        <span>{languages[source]}</span>
        {!listener && !languagesLocked && <ChevronDown size={18} aria-hidden="true" />}
      </span>
    </>
  );
  const targetLang = (
    <>
      <small>{listener ? t("hearing") : t("translated")}</small>
      <span className="lang-value">
        <span>{languages[language]}</span>
        {(listener || !languagesLocked) && <ChevronDown size={18} aria-hidden="true" />}
      </span>
    </>
  );
  const brand = session ? (
    <span className="brand">
      Translate<b>Live</b>
    </span>
  ) : (
    <a className="brand" href="/" aria-label={t("brandHome")}>
      Translate<b>Live</b>
    </a>
  );
  const sheets = (
    <>
      {sheet === "settings" && (
        <Sheet title={t("settings")} closeLabel={t("close")} onClose={() => setSheet(null)}>
          <p className="field-label">{t("settingsLanguage")}</p>
          <Segmented
            value={ui}
            label={t("settingsLanguage")}
            options={[
              { key: "de" as Lang, label: "Deutsch" },
              { key: "en" as Lang, label: "English" },
            ]}
            onChange={setUi}
          />
          <p className="field-label">{t("settingsTheme")}</p>
          <Segmented
            value={theme}
            label={t("settingsTheme")}
            options={themes.map((th) => ({ key: th.key, label: t(th.label) }))}
            onChange={setTheme}
          />
        </Sheet>
      )}
      {sheet === "join" && (
        <Sheet title={scanning ? t("joinScan") : t("joinTitle")} closeLabel={t("close")} onClose={closeJoin}>
          {scanning ? (
            <>
              <p>{t("scanHint")}</p>
              <Scanner
                onResult={(value) => {
                  setScanning(false);
                  joinLink(value);
                }}
                onError={() => {
                  setScanning(false);
                  setJoinError(t("scanDenied"));
                }}
              />
              <button className="btn btn-secondary" onClick={() => setScanning(false)}>
                <span>{t("cancel")}</span>
              </button>
            </>
          ) : (
            <>
              <p>{t("joinCodeHint")}</p>
              <form
                className="join"
                onSubmit={(e) => {
                  e.preventDefault();
                  if (joinCode.length === 4 && !joining) joinByCode(joinCode);
                }}
              >
                <input
                  className="code-input"
                  aria-label={t("joinCode")}
                  placeholder="0000"
                  inputMode="numeric"
                  pattern="[0-9]*"
                  autoComplete="one-time-code"
                  maxLength={4}
                  value={joinCode}
                  onChange={(e) => {
                    const digits = e.target.value.replace(/\D/g, "").slice(0, 4);
                    setJoinCode(digits);
                    setJoinError("");
                    if (digits.length === 4 && !joining) joinByCode(digits);
                  }}
                />
                {joinError && <p className="field-error" role="alert">{joinError}</p>}
                <button className="btn btn-primary" type="submit" disabled={joinCode.length !== 4 || joining}>
                  {joining ? <Loader2 size={18} className="spin" aria-hidden="true" /> : <Headphones size={18} />}
                  <span>{joining ? t("joining") : t("joinButton")}</span>
                </button>
              </form>
              <div className="divider" aria-hidden="true">
                <span>{t("joinOr")}</span>
              </div>
              <button className="btn btn-secondary" onClick={() => { setJoinError(""); setScanning(true); }}>
                <Camera size={18} />
                <span>{t("joinScan")}</span>
              </button>
              {linkField ? (
                <form
                  className="join"
                  onSubmit={(e) => {
                    e.preventDefault();
                    joinLink(joinText);
                  }}
                >
                  <input
                    aria-label={t("joinPlaceholder")}
                    placeholder={t("joinPlaceholder")}
                    value={joinText}
                    inputMode="url"
                    autoComplete="off"
                    autoCapitalize="off"
                    onChange={(e) => {
                      setJoinText(e.target.value);
                      setJoinError("");
                    }}
                  />
                  <button className="btn btn-secondary" type="submit" disabled={!joinText.trim()}>
                    <span>{t("joinButton")}</span>
                  </button>
                </form>
              ) : (
                <button className="textbutton centered" onClick={() => setLinkField(true)}>
                  {t("joinLinkToggle")}
                </button>
              )}
            </>
          )}
        </Sheet>
      )}
      {sheet === "language" && (
        <Sheet title={listener ? t("hearing") : t("sheetLanguages")} closeLabel={t("close")} onClose={() => setSheet(null)}>
          {listener ? (
            <p>{t("spokenIs", { lang: languages[source] })}</p>
          ) : (
            <>
              <p>{t("listenersChoose")}</p>
              <Segmented
                value={langTab}
                label={t("whichLanguage")}
                options={[
                  { key: "source" as const, label: t("spoken") },
                  { key: "target" as const, label: t("translated") },
                ]}
                onChange={setLangTab}
              />
            </>
          )}
          <div className="options" role="radiogroup" aria-label={t("language")}>
            {languageOptions.map(([code, name]) => (
              <Option
                key={code}
                label={name}
                selected={(listener || langTab === "target" ? language : source) === code}
                onSelect={() => pickLanguage(code)}
              />
            ))}
          </div>
        </Sheet>
      )}
      {sheet === "textSize" && (
        <Sheet title={t("sizeTitle")} closeLabel={t("close")} onClose={() => setSheet(null)}>
          <div className="options" role="radiogroup" aria-label={t("sizeTitle")}>
            {(Object.keys(sizes) as Size[]).map((key) => (
              <Option
                key={key}
                label={t(sizes[key].label)}
                preview={<span className="preview" style={{ fontSize: sizes[key].preview }} aria-hidden="true">Aa</span>}
                selected={size === key}
                onSelect={() => {
                  setSize(key);
                  setSheet(null);
                }}
              />
            ))}
          </div>
        </Sheet>
      )}
      {sheet === "device" && (
        <Sheet title={t("micUnnamed")} closeLabel={t("close")} onClose={() => setSheet(null)}>
          <div className="options" role="radiogroup" aria-label={t("micUnnamed")}>
            <Option label={t("micDefault")} selected={device === ""} onSelect={() => { setDevice(""); setSheet(null); }} />
            {devices.map((d) => (
              <Option
                key={d.deviceId}
                label={d.label || t("micUnnamed")}
                selected={device === d.deviceId}
                onSelect={() => {
                  setDevice(d.deviceId);
                  setSheet(null);
                }}
              />
            ))}
          </div>
        </Sheet>
      )}
      {sheet === "audio" && (
        <Sheet title={t("audioCheck")} closeLabel={t("close")} onClose={() => setSheet(null)}>
          <dl className="diag">
            <dt>{t("diagPackets")}</dt>
            <dd>{audioInfo.chunks}</dd>
            <dt>{t("diagLevel")}</dt>
            <dd>{audioInfo.peak} %</dd>
            <dt>{t("diagPlayback")}</dt>
            <dd>{audioInfo.state}</dd>
            <dt>{t("diagSound")}</dt>
            <dd>{muted ? t("diagOff") : t("diagOn")}</dd>
          </dl>
          <div className="tone">
            <button className="btn btn-secondary" onClick={testTone}>
              <Volume2 size={18} />
              <span>{t("testTone")}</span>
            </button>
            <span>{toneResult}</span>
          </div>
          <small>{t("diagRoute")}</small>
        </Sheet>
      )}
      {sheet === "share" && (
        <Sheet title={t("invite")} closeLabel={t("close")} onClose={() => setSheet(null)}>
          {code && (
            <>
              <p>{t("shareCode")}</p>
              <div className="code-big" aria-label={t("codeLabel") + " " + code}>
                {code}
              </div>
            </>
          )}
          <p>{t("shareHint")}</p>
          <div className="qr">
            {/* QR bleibt in beiden Farbschemata schwarz auf weiß, sonst scannt er nicht zuverlässig. */}
            <div>
              <QRCodeSVG value={link} size={168} level="M" bgColor="#ffffff" fgColor="#111111" />
            </div>
          </div>
          <div className="link-row">
            <input readOnly aria-label={t("shareLinkLabel")} value={link} onFocus={(e) => e.target.select()} />
            <button className="btn btn-secondary btn-icon" onClick={copy} aria-label={copied ? t("copied") : t("copy")}>
              {copied ? <Check size={18} /> : <Link size={18} />}
            </button>
          </div>
          <button className="btn btn-primary" onClick={canShare ? shareLink : copy}>
            {canShare ? <Share size={18} /> : copied ? <Check size={18} /> : <Link size={18} />}
            <span>{canShare ? t("share") : copied ? t("copied") : t("copy")}</span>
          </button>
          <small>{t("shareNetwork")}</small>
        </Sheet>
      )}
    </>
  );
  if (role === "home")
    return (
      <div className="app is-home">
        <header className="topbar">
          {brand}
          {settingsButton}
        </header>
        <main>
          <div className="column">
            <p className="intro">{t("homeIntro")}</p>
            <div className="choices">
              <button className="choice" onClick={() => setRole("speaker")}>
                <Mic size={28} aria-hidden="true" />
                <span className="choice-text">
                  <strong>{t("homeSpeak")}</strong>
                  <small>{t("homeSpeakDesc")}</small>
                </span>
                <ChevronRight size={22} aria-hidden="true" />
              </button>
              <button className="choice" onClick={() => setSheet("join")}>
                <Headphones size={28} aria-hidden="true" />
                <span className="choice-text">
                  <strong>{t("homeListen")}</strong>
                  <small>{t("homeListenDesc")}</small>
                </span>
                <ChevronRight size={22} aria-hidden="true" />
              </button>
            </div>
            <footer>
              <span>{t("footerPrivacy")}</span>
              <a href="/local-ca.cer">{t("footerCert")}</a>
            </footer>
          </div>
        </main>
        {sheets}
      </div>
    );
  return (
    <div
      className={[
        "app",
        listener ? "is-listener" : "is-speaker",
        "mode-" + (listener ? mode : "both"),
        session ? "is-session" : "is-idle",
        focus ? "is-focus" : "",
      ].join(" ")}
      style={{ "--scale": sizes[size].scale } as React.CSSProperties}
    >
      <header className="topbar">
        {focus ? (
          <>
            {stateView}
            <span className="focus-lang">{languages[language]}</span>
          </>
        ) : (
          <>
            {brand}
            <div className="topbar-right">
              {stateView}
              {settingsButton}
            </div>
          </>
        )}
      </header>
      <main>
        <div className="column">
          {!focus && (
            <div ref={route} className={"route " + status}>
              {!listener && !languagesLocked ? (
                <button className="lang lang-source" onClick={() => openLanguages("source")} aria-label={t("changeSpoken", { lang: languages[source] })}>
                  {sourceLang}
                </button>
              ) : (
                <div className="lang lang-source">{sourceLang}</div>
              )}
              <span className="route-line" aria-hidden="true" />
              {listener || !languagesLocked ? (
                <button className="lang lang-target" onClick={() => openLanguages("target")} aria-label={t(listener ? "changeHearing" : "changeTranslated", { lang: languages[language] })}>
                  {targetLang}
                </button>
              ) : (
                <div className="lang lang-target">{targetLang}</div>
              )}
            </div>
          )}
          {!session && <p className="intro">{listener ? t("introListener") : t("introSpeaker")}</p>}
          {!listener && (
            <>
              <div className="meta">
                <span>{statusLabel[status]}</span>
                {room && (
                  <span>
                    <strong>{count}</strong> {count === 1 ? t("listenersOne") : t("listenersMany")}
                  </span>
                )}
                {code && (
                  <span>
                    {t("codeLabel")} <strong className="code">{code}</strong>
                  </span>
                )}
                {devices.length > 1 && (
                  <button className="textbutton" onClick={() => setSheet("device")} disabled={active}>
                    <Mic size={14} aria-hidden="true" />
                    {deviceLabel}
                  </button>
                )}
              </div>
              <LevelMeter levels={levels} active={status === "live" && !micMuted} />
            </>
          )}
          {showAudio && !focus && (
            mode === "audio" ? (
              <div className="audio-stage">
                <LevelMeter levels={levels} active={joined} className="large" />
                <p className="status-line">{statusLabel[status]}</p>
                <button className="textbutton" onClick={() => setSheet("audio")}>
                  {t("audioCheck")}
                </button>
              </div>
            ) : (
              <>
                <div className="meta">
                  <span>{statusLabel[status]}</span>
                  <button className="textbutton" onClick={() => setSheet("audio")}>
                    {t("audioCheck")}
                  </button>
                </div>
                <LevelMeter levels={levels} active={joined} className="small" />
              </>
            )
          )}
          {!focus && alerts}
          {showText && (
            <Captions
              label={listener ? t("captionsTranslation") : t("captionsYourWords")}
              lang={listener ? languages[language] : languages[source]}
              text={listener ? text : original}
              placeholder={
                listener
                  ? joined
                    ? t("placeholderListenerJoined")
                    : t("placeholderListenerIdle")
                  : transcription === "configured"
                    ? t("placeholderSpeaker")
                    : t("placeholderNoCaptions")
              }
              endRef={transcriptEnd}
            />
          )}
          {mode === "audio" && listener && !focus && alerts}
          {!session && (
            <footer>
              <span>{t("footerPrivacy")}</span>
              <a href="/local-ca.cer">{t("footerCert")}</a>
            </footer>
          )}
        </div>
      </main>
      {focus ? (
        <button className="restore" onClick={() => setFocus(false)}>
          <ChevronUp size={18} aria-hidden="true" />
          {t("restore")}
        </button>
      ) : (
        <div className="dock">
          <div className="dock-inner">
            {listener && (
              <Segmented
                value={mode}
                label={t("modeGroup")}
                options={modes.map((m) => ({ key: m.key, label: t(m.label), icon: m.icon }))}
                onChange={switchMode}
              />
            )}
            <div className="dock-row">
              {listener ? (
                !joined ? (
                  <button className="btn btn-primary" onClick={start}>
                    {mode === "text" ? <BookOpen size={18} /> : <Headphones size={18} />}
                    <span>{mode === "text" ? t("startRead") : t("startListen")}</span>
                  </button>
                ) : mode === "text" ? (
                  <>
                    <button className="btn btn-secondary" onClick={() => setSheet("textSize")}>
                      <ALargeSmall size={20} />
                      <span>{t(sizes[size].short)}</span>
                    </button>
                    <button className="btn btn-secondary" onClick={() => setFocus(true)}>
                      <Maximize2 size={18} />
                      <span>{t("focus")}</span>
                    </button>
                    <button className="btn btn-secondary" onClick={stop} disabled={busy}>
                      <LogOut size={18} />
                      <span>{t("leave")}</span>
                    </button>
                  </>
                ) : (
                  <>
                    <button className="btn btn-secondary" onClick={() => setAudio(muted)} aria-pressed={muted}>
                      {muted ? <VolumeX size={20} /> : <Volume2 size={20} />}
                      <span>{muted ? t("soundOn") : t("soundOff")}</span>
                    </button>
                    <button className="btn btn-secondary" onClick={stop} disabled={busy}>
                      {busy ? <Loader2 size={18} className="spin" aria-hidden="true" /> : <LogOut size={18} />}
                      <span>{status === "connecting" ? t("statusConnecting") : t("leave")}</span>
                    </button>
                  </>
                )
              ) : !active ? (
                <>
                  <button className="btn btn-primary" onClick={start}>
                    <Mic size={18} />
                    <span>{status === "ended" ? t("resume") : t("start")}</span>
                  </button>
                  {room && (
                    <button className="btn btn-secondary btn-icon" onClick={() => setSheet("share")} aria-label={t("invite")}>
                      <Share size={20} />
                    </button>
                  )}
                </>
              ) : (
                <>
                  {status === "live" && (
                    <button className="btn btn-secondary" onClick={() => setMic(micMuted)} aria-pressed={micMuted}>
                      {micMuted ? <MicOff size={18} /> : <Mic size={18} />}
                      <span>{micMuted ? t("micOn") : t("micOff")}</span>
                    </button>
                  )}
                  <button className="btn btn-secondary" onClick={stop} disabled={busy}>
                    {busy ? <Loader2 size={18} className="spin" aria-hidden="true" /> : <Square size={14} fill="currentColor" />}
                    <span>
                      {status === "connecting"
                        ? t("statusConnecting")
                        : status === "draining"
                          ? t("statusDraining")
                          : t("stopShort")}
                    </span>
                  </button>
                  {room && (
                    <button className="btn btn-secondary btn-icon" onClick={() => setSheet("share")} aria-label={t("invite")}>
                      <Share size={20} />
                    </button>
                  )}
                </>
              )}
            </div>
          </div>
        </div>
      )}
      {sheets}
    </div>
  );
}
createRoot(document.getElementById("root")!).render(<App />);
