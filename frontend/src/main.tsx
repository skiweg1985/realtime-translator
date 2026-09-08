import React, { useEffect, useRef, useState } from "react";
import { flushSync } from "react-dom";
import { createRoot } from "react-dom/client";
import {
  Mic,
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
  Link,
  Share,
  Loader2,
  AlertCircle,
  Info,
  ALargeSmall,
  Maximize2,
  LogOut,
} from "lucide-react";
import { QRCodeSVG } from "qrcode.react";
import "@fontsource-variable/inter/opsz.css";
import "./style.css";

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
type Mode = "both" | "audio" | "text";
type Size = "normal" | "large" | "xl";
type SheetKind = "language" | "share" | "textSize" | "device" | "audio" | null;
const sizes: Record<Size, { label: string; short: string; scale: number; preview: number }> = {
  normal: { label: "Normal", short: "Normal", scale: 1, preview: 17 },
  large: { label: "Groß", short: "Groß", scale: 1.25, preview: 22 },
  xl: { label: "Extra groß", short: "XL", scale: 1.6, preview: 28 },
};
const modes: { key: Mode; label: string; icon: React.ReactNode }[] = [
  { key: "both", label: "Ton + Text", icon: <CaptionsIcon size={20} /> },
  { key: "audio", label: "Ton", icon: <Headphones size={20} /> },
  { key: "text", label: "Text", icon: <BookOpen size={20} /> },
];
const LEVELS = 48;

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

/* Browser-Fehler beim Mikrofonzugriff in verständliche Hinweise übersetzen. */
function describeError(e: unknown) {
  const name = e instanceof DOMException ? e.name : "";
  if (name === "NotAllowedError" || name === "PermissionDeniedError")
    return "Mikrofonzugriff wurde abgelehnt. Bitte in den Browser-Einstellungen erlauben.";
  if (name === "NotFoundError" || name === "OverconstrainedError")
    return "Kein passendes Mikrofon gefunden. Bitte ein anderes Gerät wählen.";
  if (name === "NotReadableError")
    return "Das Mikrofon wird gerade von einer anderen App verwendet.";
  return e instanceof Error && e.message
    ? e.message
    : "Mikrofon konnte nicht gestartet werden.";
}

function reducedMotion() {
  return window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}

/* Pegelanzeige aus echten Audiodaten: die letzten Werte als Balken. */
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
      // Ruhende Grundlinie; bei Ton wachsen die Balken daraus heraus.
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
  onClose,
  children,
}: {
  title: string;
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
          <button className="close" onClick={onClose} aria-label="Schließen">
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

function App() {
  const params = new URLSearchParams(location.hash.slice(1));
  const [room, setRoom] = useState(params.get("room") || "");
  const [owner, setOwner] = useState(
    sessionStorage.getItem("owner:" + room) || "",
  );
  const listener = !!room && !owner;
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
    [elapsed, setElapsed] = useState(0);
  const [audioInfo, setAudioInfo] = useState({ chunks: 0, peak: 0, state: "nicht gestartet" });
  const [toneResult, setToneResult] = useState("");
  const [transcription, setTranscription] = useState("loading");
  const [devices, setDevices] = useState<MediaDeviceInfo[]>([]),
    [device, setDevice] = useState("");
  const [mode, setMode] = useState<Mode>("both");
  const [size, setSize] = useState<Size>(() => {
    try {
      const saved = localStorage.getItem("translate:size");
      return saved && saved in sizes ? (saved as Size) : "normal";
    } catch {
      return "normal";
    }
  });
  const [focus, setFocus] = useState(false);
  const [sheet, setSheet] = useState<SheetKind>(null);
  const [langTab, setLangTab] = useState<"source" | "target">("target");
  const socket = useRef<WebSocket | null>(null),
    context = useRef<AudioContext | null>(null),
    stream = useRef<MediaStream | null>(null);
  const capture = useRef<AudioWorkletNode | null>(null),
    nextAudio = useRef(0),
    audioGain = useRef<GainNode | null>(null);
  const route = useRef<HTMLDivElement>(null),
    levels = useRef(new Float32Array(LEVELS)),
    running = useRef(false),
    wake = useRef<any>(null);
  const transcriptEnd = useRef<HTMLDivElement>(null);
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
  useEffect(() => {
    try {
      localStorage.setItem("translate:size", size);
    } catch {}
  }, [size]);
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
      setNotice("Die Audioausgabe hängt zurück. Bitte erneut beitreten.");
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
        if (!navigator.mediaDevices?.getUserMedia)
          throw Error(
            "Mikrofon benötigt HTTPS und ein vertrauenswürdiges Zertifikat.",
          );
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
          if (!response.ok)
            throw Error(data.detail || "Sitzung konnte nicht erstellt werden.");
          id = data.id;
          secret = data.owner;
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
              if (ws.bufferedAmount > 48000) {
                setError(
                  "Die Verbindung ist zu langsam. Bitte erneut starten.",
                );
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
        setError(
          "Verbindung fehlgeschlagen. Bitte Netzwerk und Zertifikat prüfen.",
        );
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
  async function copy() {
    try {
      await navigator.clipboard.writeText(link);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      setNotice("Bitte den Link im Teilen-Fenster kopieren.");
    }
  }
  async function shareLink() {
    try {
      await navigator.share({ title: "Translate Live", url: link });
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
      setToneResult("Testton abgespielt · " + ctx.state);
    } catch { setToneResult("Safari hat den Testton blockiert."); }
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
  const statusLabel: Record<Status, string> = {
    idle: listener ? "Noch nicht verbunden" : "Bereit",
    connecting: "Verbindet …",
    live: listener ? "Live" : "Live, du wirst übersetzt",
    waiting: "Wartet auf den Sprecher",
    ended: "Pausiert",
    draining: "Wird beendet …",
    error: "Sprache gerade nicht verfügbar",
  };
  const stateLabel: Record<Status, string> = {
    idle: "Bereit",
    connecting: "Verbindet",
    live: "Live",
    waiting: "Wartet",
    ended: "Pausiert",
    draining: "Beendet",
    error: "Unterbrochen",
  };
  const deviceLabel =
    devices.find((d) => d.deviceId === device)?.label || "Standardmikrofon";
  const showText = listener ? mode !== "audio" : true;
  const showAudio = listener && mode !== "text";
  const stateView = (
    <div className={"state " + status} role="status">
      <span className="state-dot" aria-hidden="true" />
      <span>{stateLabel[status]}</span>
      {status === "live" && <span className="timer">{clock}</span>}
    </div>
  );
  const alerts = (
    <>
      {error && (
        <div className="alert" role="alert">
          <AlertCircle size={18} aria-hidden="true" />
          <span>{error}</span>
          <button className="dismiss" onClick={() => setError("")} aria-label="Meldung schließen">
            <X size={18} />
          </button>
        </div>
      )}
      {notice && (
        <div className="notice">
          <Info size={18} aria-hidden="true" />
          <span>{notice}</span>
          <button className="dismiss" onClick={() => setNotice("")} aria-label="Hinweis schließen">
            <X size={18} />
          </button>
        </div>
      )}
    </>
  );
  const sourceLang = (
    <>
      <small>Gesprochen</small>
      <span className="lang-value">
        <span>{languages[source]}</span>
        {!listener && !languagesLocked && <ChevronDown size={18} aria-hidden="true" />}
      </span>
    </>
  );
  const targetLang = (
    <>
      <small>{listener ? "Ich höre" : "Übersetzt"}</small>
      <span className="lang-value">
        <span>{languages[language]}</span>
        {(listener || !languagesLocked) && <ChevronDown size={18} aria-hidden="true" />}
      </span>
    </>
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
            <a className="brand" href="/" aria-label="Translate Live, Startseite">
              Translate<b>Live</b>
            </a>
            {stateView}
          </>
        )}
      </header>
      <main>
        <div className="column">
          {!focus && (
            <div ref={route} className={"route " + status}>
              {!listener && !languagesLocked ? (
                <button className="lang lang-source" onClick={() => openLanguages("source")} aria-label={"Gesprochene Sprache: " + languages[source] + ", ändern"}>
                  {sourceLang}
                </button>
              ) : (
                <div className="lang lang-source">{sourceLang}</div>
              )}
              <span className="route-line" aria-hidden="true" />
              {listener || !languagesLocked ? (
                <button className="lang lang-target" onClick={() => openLanguages("target")} aria-label={(listener ? "Ich höre " : "Übersetzt nach ") + languages[language] + ", ändern"}>
                  {targetLang}
                </button>
              ) : (
                <div className="lang lang-target">{targetLang}</div>
              )}
            </div>
          )}
          {!session && (
            <p className="intro">
              {listener
                ? "Du hörst die Übersetzung und liest mit. Unten wählst du Ton, Text oder beides."
                : "Sprich normal. Zuhörer hören die Übersetzung und lesen mit."}
            </p>
          )}
          {!listener && (
            <>
              <div className="meta">
                <span>{statusLabel[status]}</span>
                {room && (
                  <span>
                    <strong>{count}</strong> {count === 1 ? "Zuhörer" : "Zuhörer"}
                  </span>
                )}
                {devices.length > 1 && (
                  <button className="textbutton" onClick={() => setSheet("device")} disabled={active}>
                    <Mic size={14} aria-hidden="true" />
                    {deviceLabel}
                  </button>
                )}
              </div>
              <LevelMeter levels={levels} active={status === "live"} />
            </>
          )}
          {showAudio && !focus && (
            mode === "audio" ? (
              <div className="audio-stage">
                <LevelMeter levels={levels} active={joined} className="large" />
                <p className="status-line">{statusLabel[status]}</p>
                <button className="textbutton" onClick={() => setSheet("audio")}>
                  Audio prüfen
                </button>
              </div>
            ) : (
              <>
                <div className="meta">
                  <span>{statusLabel[status]}</span>
                  <button className="textbutton" onClick={() => setSheet("audio")}>
                    Audio prüfen
                  </button>
                </div>
                <LevelMeter levels={levels} active={joined} className="small" />
              </>
            )
          )}
          {!focus && alerts}
          {showText && (
            <Captions
              label={listener ? "Übersetzung" : "Deine Worte"}
              lang={listener ? languages[language] : languages[source]}
              text={listener ? text : original}
              placeholder={
                listener
                  ? joined
                    ? "Sobald gesprochen wird, steht die Übersetzung hier."
                    : "Die Übersetzung erscheint hier, sobald du dabei bist."
                  : transcription === "configured"
                    ? "Deine gesprochenen Worte erscheinen hier mit kurzer Verzögerung."
                    : "Die Spracherkennung ist nicht eingerichtet. Übersetzen geht trotzdem."
              }
              endRef={transcriptEnd}
            />
          )}
          {mode === "audio" && listener && !focus && alerts}
          {!session && (
            <footer>
              <span>Keine Anmeldung · Keine Aufzeichnung</span>
              <a href="/local-ca.cer">iPhone-Zertifikat</a>
            </footer>
          )}
        </div>
      </main>
      {focus ? (
        <button className="restore" onClick={() => setFocus(false)}>
          <ChevronUp size={18} aria-hidden="true" />
          Steuerung anzeigen
        </button>
      ) : (
        <div className="dock">
          <div className="dock-inner">
            {listener && (
              <div className="segmented" role="radiogroup" aria-label="Was du bekommst">
                {modes.map((m) => (
                  <button key={m.key} role="radio" aria-checked={mode === m.key} onClick={() => switchMode(m.key)}>
                    {m.icon}
                    {m.label}
                  </button>
                ))}
              </div>
            )}
            <div className="dock-row">
              {listener ? (
                !joined ? (
                  <button className="btn btn-primary" onClick={start}>
                    {mode === "text" ? <BookOpen size={18} /> : <Headphones size={18} />}
                    <span>{mode === "text" ? "Mitlesen starten" : "Zuhören starten"}</span>
                  </button>
                ) : mode === "text" ? (
                  <>
                    <button className="btn btn-secondary" onClick={() => setSheet("textSize")}>
                      <ALargeSmall size={20} />
                      <span>{sizes[size].short}</span>
                    </button>
                    <button className="btn btn-secondary" onClick={() => setFocus(true)}>
                      <Maximize2 size={18} />
                      <span>Fokus</span>
                    </button>
                    <button className="btn btn-secondary" onClick={stop} disabled={busy}>
                      <LogOut size={18} />
                      <span>Verlassen</span>
                    </button>
                  </>
                ) : (
                  <>
                    <button className="btn btn-secondary" onClick={() => setAudio(muted)} aria-pressed={muted}>
                      {muted ? <VolumeX size={20} /> : <Volume2 size={20} />}
                      <span>{muted ? "Ton an" : "Ton aus"}</span>
                    </button>
                    <button className="btn btn-secondary" onClick={stop} disabled={busy}>
                      {busy ? <Loader2 size={18} className="spin" aria-hidden="true" /> : <LogOut size={18} />}
                      <span>{status === "connecting" ? "Verbindet …" : "Verlassen"}</span>
                    </button>
                  </>
                )
              ) : (
                <>
                  {!active ? (
                    <button className="btn btn-primary" onClick={start}>
                      <Mic size={18} />
                      <span>{status === "ended" ? "Weiter sprechen" : "Sprechen starten"}</span>
                    </button>
                  ) : (
                    <button className="btn btn-secondary" onClick={stop} disabled={busy}>
                      {busy ? <Loader2 size={18} className="spin" aria-hidden="true" /> : <Square size={14} fill="currentColor" />}
                      <span>
                        {status === "connecting"
                          ? "Verbindet …"
                          : status === "draining"
                            ? "Wird beendet …"
                            : "Sprechen beenden"}
                      </span>
                    </button>
                  )}
                  {room && (
                    <button className="btn btn-secondary btn-icon" onClick={() => setSheet("share")} aria-label="Zuhörer einladen">
                      <Share size={20} />
                    </button>
                  )}
                </>
              )}
            </div>
          </div>
        </div>
      )}
      {sheet === "language" && (
        <Sheet title={listener ? "Ich höre" : "Sprachen"} onClose={() => setSheet(null)}>
          {listener ? (
            <p>Gesprochen wird {languages[source]}. Wähle, in welcher Sprache du hören und lesen willst.</p>
          ) : (
            <>
              <p>Zuhörer können ihre Sprache später selbst wählen.</p>
              <div className="segmented" role="radiogroup" aria-label="Welche Sprache ändern">
                <button role="radio" aria-checked={langTab === "source"} onClick={() => setLangTab("source")}>
                  Gesprochen
                </button>
                <button role="radio" aria-checked={langTab === "target"} onClick={() => setLangTab("target")}>
                  Übersetzt
                </button>
              </div>
            </>
          )}
          <div className="options" role="radiogroup" aria-label="Sprache">
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
        <Sheet title="Textgröße" onClose={() => setSheet(null)}>
          <div className="options" role="radiogroup" aria-label="Textgröße">
            {(Object.keys(sizes) as Size[]).map((key) => (
              <Option
                key={key}
                label={sizes[key].label}
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
        <Sheet title="Mikrofon" onClose={() => setSheet(null)}>
          <div className="options" role="radiogroup" aria-label="Mikrofon">
            <Option label="Standardmikrofon" selected={device === ""} onSelect={() => { setDevice(""); setSheet(null); }} />
            {devices.map((d) => (
              <Option
                key={d.deviceId}
                label={d.label || "Mikrofon"}
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
        <Sheet title="Audio prüfen" onClose={() => setSheet(null)}>
          <dl className="diag">
            <dt>Audio-Pakete</dt>
            <dd>{audioInfo.chunks}</dd>
            <dt>Pegel</dt>
            <dd>{audioInfo.peak} %</dd>
            <dt>Wiedergabe</dt>
            <dd>{audioInfo.state}</dd>
            <dt>Ton</dt>
            <dd>{muted ? "aus" : "an"}</dd>
          </dl>
          <div className="tone">
            <button className="btn btn-secondary" onClick={testTone}>
              <Volume2 size={18} />
              <span>Testton</span>
            </button>
            <span>{toneResult}</span>
          </div>
          <small>Ton kommt über die aktuell gewählten Lautsprecher oder Kopfhörer.</small>
        </Sheet>
      )}
      {sheet === "share" && (
        <Sheet title="Zuhörer einladen" onClose={() => setSheet(null)}>
          <p>QR-Code scannen oder Link öffnen, dann auf „Zuhören starten“ tippen.</p>
          <div className="qr">
            {/* QR bleibt in beiden Farbschemata schwarz auf weiß, sonst scannt er nicht zuverlässig. */}
            <div>
              <QRCodeSVG value={link} size={168} level="M" bgColor="#ffffff" fgColor="#111111" />
            </div>
          </div>
          <div className="link-row">
            <input readOnly aria-label="Zuhörerlink" value={link} onFocus={(e) => e.target.select()} />
            <button className="btn btn-secondary btn-icon" onClick={copy} aria-label={copied ? "Link kopiert" : "Link kopieren"}>
              {copied ? <Check size={18} /> : <Link size={18} />}
            </button>
          </div>
          <button className="btn btn-primary" onClick={canShare ? shareLink : copy}>
            {canShare ? <Share size={18} /> : copied ? <Check size={18} /> : <Link size={18} />}
            <span>{canShare ? "Link teilen" : copied ? "Link kopiert" : "Link kopieren"}</span>
          </button>
          <small>Im selben Netzwerk. Auf dem iPhone zuerst das lokale Zertifikat installieren und ihm vertrauen.</small>
        </Sheet>
      )}
    </div>
  );
}
createRoot(document.getElementById("root")!).render(<App />);
