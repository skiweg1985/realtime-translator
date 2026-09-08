import React, { useEffect, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import {
  Mic,
  Headphones,
  AudioLines,
  Link,
  Check,
  Square,
  Volume2,
  VolumeX,
  X,
  ChevronDown,
  ChevronRight,
  Radio,
  ArrowRight,
  Lock,
  Loader2,
  AlertCircle,
  Info,
  Share,
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

/* Gestylter Chip mit unsichtbarem nativem select darüber: iOS zeigt seinen Picker. */
function ChipSelect({
  label,
  value,
  options,
  disabled,
  onChange,
  className = "",
}: {
  label: string;
  value: string;
  options: [string, string][];
  disabled?: boolean;
  onChange: (value: string) => void;
  className?: string;
}) {
  const current = options.find(([k]) => k === value)?.[1] ?? value;
  return (
    <label className={"chip " + (disabled ? "is-locked " : "") + className}>
      <span className="chip-label">{label}</span>
      <span className="chip-value">{current}</span>
      <span className="chip-icon" aria-hidden="true">
        {disabled ? <Lock size={13} /> : <ChevronDown size={16} />}
      </span>
      <select
        aria-label={label}
        value={value}
        disabled={disabled}
        onChange={(e) => onChange(e.target.value)}
      >
        {options.map(([k, v]) => (
          <option key={k} value={k}>
            {v}
          </option>
        ))}
      </select>
    </label>
  );
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
    [share, setShare] = useState(false),
    [copied, setCopied] = useState(false);
  const [muted, setMuted] = useState(false),
    [elapsed, setElapsed] = useState(0);
  const [audioInfo, setAudioInfo] = useState({ chunks: 0, peak: 0, state: "nicht gestartet" });
  const [toneResult, setToneResult] = useState("");
  const [transcription, setTranscription] = useState("loading");
  const [devices, setDevices] = useState<MediaDeviceInfo[]>([]),
    [device, setDevice] = useState("");
  const [drag, setDrag] = useState(0);
  const socket = useRef<WebSocket | null>(null),
    context = useRef<AudioContext | null>(null),
    stream = useRef<MediaStream | null>(null);
  const capture = useRef<AudioWorkletNode | null>(null),
    nextAudio = useRef(0),
    audioGain = useRef<GainNode | null>(null);
  const orb = useRef<HTMLDivElement>(null),
    running = useRef(false),
    wake = useRef<any>(null);
  const transcriptEnd = useRef<HTMLDivElement>(null);
  const sheet = useRef<HTMLElement>(null),
    dragStart = useRef<number | null>(null),
    dragNow = useRef(0);
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
  }, [text, original]);
  useEffect(() => {
    if (!share) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") closeShare();
    };
    document.addEventListener("keydown", onKey);
    const previous = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.removeEventListener("keydown", onKey);
      document.body.style.overflow = previous;
    };
  }, [share]);
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
  const link = location.origin + "/#room=" + room;
  const canShare =
    typeof navigator !== "undefined" && typeof navigator.share === "function";
  const clock =
    Math.floor(elapsed / 60) + ":" + String(elapsed % 60).padStart(2, "0");
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
    if (orb.current)
      orb.current.style.setProperty(
        "--energy",
        String(0.25 + Math.random() * 0.5),
      );
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
              orb.current?.style.setProperty(
                "--energy",
                String(Math.min(1, Math.sqrt(energy / samples.length) / 5000)),
              );
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
      await navigator.share({ title: "translate live", url: link });
    } catch {
      /* Abgebrochen oder nicht erlaubt: kein Fehler für den Nutzer. */
    }
  }
  function closeShare() {
    setShare(false);
    setDrag(0);
    dragStart.current = null;
    dragNow.current = 0;
  }
  function onTouchStart(e: React.TouchEvent<HTMLElement>) {
    if (sheet.current && sheet.current.scrollTop > 0) return;
    dragStart.current = e.touches[0].clientY;
    dragNow.current = 0;
  }
  function onTouchMove(e: React.TouchEvent<HTMLElement>) {
    if (dragStart.current === null) return;
    const dy = Math.max(0, e.touches[0].clientY - dragStart.current);
    dragNow.current = dy;
    setDrag(dy);
  }
  function onTouchEnd() {
    if (dragStart.current === null) return;
    dragStart.current = null;
    if (dragNow.current > 80) closeShare();
    else setDrag(0);
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
  function toggleMute() {
    setMuted(!muted);
    if (audioGain.current) audioGain.current.gain.value = muted ? 1 : 0;
  }
  const statusLabel: Record<Status, string> = {
    idle: listener ? "Bereit zum Zuhören" : "Bereit, wenn du es bist",
    connecting: "Verbindung wird aufgebaut",
    live: listener ? "Du bist live dabei" : "Deine Stimme verbindet",
    waiting: "Warte auf den Sprecher",
    ended: "Sitzung pausiert",
    draining: "Letzte Worte werden übersetzt",
    error: "Diese Sprache ist momentan nicht verfügbar",
  };
  const pillLabel: Record<Status, string> = {
    idle: "Bereit",
    connecting: "Verbindet",
    live: "Live",
    waiting: "Wartet",
    ended: "Pausiert",
    draining: "Beendet",
    error: "Unterbrochen",
  };
  return (
    <div className="app">
      <header className="topbar glass">
        <div className="topbar-inner">
          <a className="brand" href="/" aria-label="translate live, Startseite">
            <span className="brand-icon">
              <AudioLines size={18} />
            </span>
            <span className="brand-name">
              translate<span>live</span>
            </span>
          </a>
          <div className={"status-pill " + status} role="status">
            <span className="status-dot" aria-hidden="true" />
            <span>{pillLabel[status]}</span>
            {status === "live" && <span className="timer">{clock}</span>}
          </div>
        </div>
      </header>
      <main>
        <section className="hero">
          <h1>
            {listener ? (
              <>
                Deine Sprache.
                <br />
                <span>Alle verbunden.</span>
              </>
            ) : (
              <>
                Deine Worte.
                <br />
                <span>Ohne Sprachgrenzen.</span>
              </>
            )}
          </h1>
          <p className="intro">
            {listener
              ? "Hör die Übersetzung live. Oder lies einfach mit."
              : "Sprich ganz natürlich. Andere hören und lesen live mit."}
          </p>
        </section>
        <div className="language-row glass">
          <ChipSelect
            label="Gesprochen"
            value={source}
            options={languageOptions}
            disabled={!!room}
            onChange={setSource}
          />
          <ArrowRight size={16} className="language-arrow" aria-hidden="true" />
          <ChipSelect
            label={listener ? "Ich höre" : "Standardsprache"}
            value={language}
            options={languageOptions}
            disabled={!listener && !!room}
            onChange={chooseLanguage}
          />
        </div>
        <section className="stage" aria-label="Live-Audio">
          <div
            ref={orb}
            className={"orb " + (status === "live" ? "is-live" : "")}
          >
            <div className="orb-inner" />
            <div className="wave">
              {[0, 1, 2, 3, 4, 5, 6].map((i) => (
                <i key={i} style={{ "--i": i } as React.CSSProperties} />
              ))}
            </div>
          </div>
          <p className="status" role="status">
            {statusLabel[status]}
          </p>
          <div className="controls glass">
            {!active && status !== "waiting" ? (
              <button className="primary" onClick={start}>
                {listener ? <Headphones size={18} /> : <Mic size={18} />}
                {listener
                  ? "Live zuhören"
                  : status === "ended"
                    ? "Weiter sprechen"
                    : "Sprechen starten"}
              </button>
            ) : (
              <button className="primary stop" disabled={busy} onClick={stop}>
                {busy ? (
                  <Loader2 size={18} className="spin" aria-hidden="true" />
                ) : (
                  <Square size={14} fill="currentColor" />
                )}
                {status === "connecting"
                  ? "Verbinden …"
                  : status === "draining"
                    ? "Wird abgeschlossen …"
                    : listener
                      ? "Verlassen"
                      : "Sprechen beenden"}
              </button>
            )}
            {listener && (
              <button
                className="icon-button glass"
                onClick={toggleMute}
                aria-pressed={muted}
                aria-label={muted ? "Ton einschalten" : "Ton stummschalten"}
              >
                {muted ? <VolumeX size={20} /> : <Volume2 size={20} />}
              </button>
            )}
            {!listener && room && (
              <button
                className="icon-button glass"
                onClick={() => setShare(true)}
                aria-label="Zuhörer einladen"
              >
                <Link size={20} />
              </button>
            )}
          </div>
          <p className="hint">
            {listener
              ? "Audio über die aktuell gewählten Lautsprecher oder Kopfhörer."
              : room
                ? `${count} ${count === 1 ? "Person hört" : "Personen hören"} zu · Link teilen und gemeinsam starten`
                : "Handy, Mikrofon oder AirPods. Ein Fingertipp genügt."}
          </p>
          {!listener && devices.length > 1 && (
            <ChipSelect
              className="standalone glass"
              label="Mikrofon"
              value={device}
              disabled={active}
              options={[
                ["", "Standardmikrofon"],
                ...devices.map(
                  (d) => [d.deviceId, d.label || "Mikrofon"] as [string, string],
                ),
              ]}
              onChange={setDevice}
            />
          )}
          {listener && (
            <details className="audio-check glass">
              <summary>
                Audio prüfen
                <ChevronDown size={16} aria-hidden="true" />
              </summary>
              <div className="audio-body">
                <dl>
                  <dt>Audio-Pakete</dt>
                  <dd>{audioInfo.chunks}</dd>
                  <dt>Pegel</dt>
                  <dd>{audioInfo.peak} %</dd>
                  <dt>Wiedergabe</dt>
                  <dd>{audioInfo.state}</dd>
                  <dt>Ton</dt>
                  <dd>{muted ? "stumm" : "an"}</dd>
                </dl>
                <div className="tone">
                  <button className="secondary glass" onClick={testTone}>
                    <Volume2 size={16} />
                    Testton
                  </button>
                  <span>{toneResult}</span>
                </div>
              </div>
            </details>
          )}
        </section>
        {error && (
          <div className="alert" role="alert">
            <AlertCircle size={18} aria-hidden="true" />
            <span>{error}</span>
            <button
              className="dismiss"
              onClick={() => setError("")}
              aria-label="Meldung schließen"
            >
              <X size={18} />
            </button>
          </div>
        )}
        {notice && (
          <div className="notice">
            <Info size={18} aria-hidden="true" />
            <span>{notice}</span>
            <button
              className="dismiss"
              onClick={() => setNotice("")}
              aria-label="Hinweis schließen"
            >
              <X size={18} />
            </button>
          </div>
        )}
        <section className="transcripts single">
          {!listener && (
            <article className="card glass">
              <div className="card-label">
                <Mic size={15} />
                Deine Worte
                <span className="tag">{languages[source]}</span>
              </div>
              <div className="transcript" aria-live="polite">
                {original || (
                  <span className="placeholder">
                    {transcription === "configured"
                      ? "Deine gesprochenen Worte erscheinen hier mit kurzer Verzögerung."
                      : "Die Cloud-Spracherkennung ist nicht eingerichtet. Übersetzen ist weiterhin möglich."}
                  </span>
                )}
                <div ref={listener ? undefined : transcriptEnd} />
              </div>
            </article>
          )}
          {listener && <article className="card glass translation">
            <div className="card-label">
              <AudioLines size={15} />
              Live-Übersetzung
              <span className="tag">{languages[language]}</span>
            </div>
            <div className="transcript" aria-live="polite">
              {text || (
                <span className="placeholder">
                  {listener
                    ? "Sobald gesprochen wird, erscheinen die übersetzten Worte hier."
                    : "Hier entsteht die Übersetzung. Wort für Wort."}
                </span>
              )}
              <div ref={transcriptEnd} />
            </div>
          </article>}
        </section>
        {room && !listener && (
          <button className="invite glass" onClick={() => setShare(true)}>
            <span className="tile">
              <Radio size={20} />
            </span>
            <span className="text">
              <strong>Zuhörer einladen</strong>
              <small>Ein Link. Beliebige Geräte. Gemeinsam zuhören.</small>
            </span>
            <ChevronRight size={20} aria-hidden="true" />
          </button>
        )}
      </main>
      <footer>
        <span>Keine Anmeldung · Keine dauerhafte Aufzeichnung</span>
        <span>
          <span>LiteLLM Translate</span>
          <a href="/local-ca.cer">iPhone-Zertifikat</a>
        </span>
      </footer>
      {share && (
        <div className="sheet-backdrop" onClick={closeShare}>
          <section
            ref={sheet}
            className={"sheet glass " + (drag > 0 ? "is-dragging" : "")}
            role="dialog"
            aria-modal="true"
            aria-label="Sitzung teilen"
            style={drag > 0 ? { transform: `translateY(${drag}px)` } : undefined}
            onClick={(e) => e.stopPropagation()}
            onTouchStart={onTouchStart}
            onTouchMove={onTouchMove}
            onTouchEnd={onTouchEnd}
            onTouchCancel={onTouchEnd}
          >
            <div className="grabber" aria-hidden="true" />
            <button
              className="close icon-button"
              onClick={closeShare}
              aria-label="Schließen"
            >
              <X size={20} />
            </button>
            <h2>Gemeinsam zuhören.</h2>
            <p>
              QR-Code scannen oder Link öffnen.
              <br />
              Dann auf „Live zuhören“ tippen.
            </p>
            <div className="qr">
              {/* QR bleibt in beiden Farbschemata schwarz auf weiß, sonst scannt er nicht zuverlässig. */}
              <QRCodeSVG value={link} size={168} level="M" bgColor="#ffffff" fgColor="#111111" />
            </div>
            <div className="link-row">
              <input
                readOnly
                aria-label="Zuhörerlink"
                value={link}
                onFocus={(e) => e.target.select()}
              />
              <button
                className="icon-button glass"
                onClick={copy}
                aria-label={copied ? "Link kopiert" : "Link kopieren"}
              >
                {copied ? <Check size={18} /> : <Link size={18} />}
              </button>
            </div>
            <button className="primary" onClick={canShare ? shareLink : copy}>
              {canShare ? (
                <Share size={18} />
              ) : copied ? (
                <Check size={18} />
              ) : (
                <Link size={18} />
              )}
              {canShare ? "Link teilen" : copied ? "Link kopiert" : "Link kopieren"}
            </button>
            <small>
              Im selben Netzwerk. Auf dem iPhone zuerst das lokale Zertifikat
              installieren und ihm vertrauen.
            </small>
          </section>
        </div>
      )}
    </div>
  );
}
createRoot(document.getElementById("root")!).render(<App />);
