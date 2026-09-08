import React, { useEffect, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import {
  Mic,
  ArrowUpRight,
  Headphones,
  AudioLines,
  Link,
  Check,
  Square,
  Volume2,
  VolumeX,
  X,
  ChevronDown,
  Radio,
  ArrowRight,
} from "lucide-react";
import { QRCodeSVG } from "qrcode.react";
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
type Status = "idle" | "connecting" | "live" | "waiting" | "ended" | "draining";
function App() {
  const params = new URLSearchParams(location.hash.slice(1));
  const [room, setRoom] = useState(params.get("room") || "");
  const [owner, setOwner] = useState(
    sessionStorage.getItem("owner:" + room) || "",
  );
  const listener = !!room && !owner;
  const [source, setSource] = useState("de"),
    [language, setLanguage] = useState("en");
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
  useEffect(() => {
    fetch("/api/health")
      .then((r) => r.json())
      .then((x) => setTranscription(x.transcription));
    if (room)
      fetch("/api/rooms/" + room)
        .then(async (r) => {
          const x = await r.json();
          if (!r.ok) throw Error(x.detail);
          setLanguage(x.language);
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
    if (box && text) box.scrollTop = box.scrollHeight;
  }, [text, original]);
  useEffect(
    () => () => {
      socket.current?.close();
      stopMic();
      context.current?.close();
    },
    [],
  );
  const active = ["connecting", "live", "draining"].includes(status);
  const link = location.origin + "/#room=" + room;
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
  async function start() {
    setError("");
    setNotice("");
    setElapsed(0);
    setStatus("connecting");
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
        "wss://" + location.host + "/api/rooms/" + id + "/ws",
      );
      socket.current = ws;
      ws.onopen = () =>
        ws.send(
          JSON.stringify(
            listener
              ? { role: "listener" }
              : { role: "speaker", owner: secret },
          ),
        );
      ws.onmessage = (message) => {
        const event = JSON.parse(message.data);
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
      ws.onerror = () =>
        setError(
          "Verbindung fehlgeschlagen. Bitte Netzwerk und Zertifikat prüfen.",
        );
      ws.onclose = () => {
        stopMic();
        setStatus((s) => (s === "idle" ? "idle" : "ended"));
      };
    } catch (e) {
      stopMic();
      setStatus("idle");
      setError(
        e instanceof Error
          ? e.message
          : "Mikrofon konnte nicht gestartet werden.",
      );
    }
  }
  function stop() {
    stopMic();
    if (listener) {
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
    idle: "Bereit, wenn du es bist",
    connecting: "Verbindung wird aufgebaut",
    live: listener ? "Du bist live dabei" : "Deine Stimme verbindet",
    waiting: "Warte auf den Sprecher",
    ended: "Sitzung pausiert",
    draining: "Letzte Worte werden übersetzt",
  };
  return (
    <div className="app">
      <header>
        <a className="brand" href="/">
          <span className="brand-icon">
            <AudioLines size={21} />
          </span>
          translate<span className="brand-dot">live</span>
        </a>
        <span className="endpoint">
          <span /> LiteLLM Translate
        </span>
      </header>
      <main>
        <div className="eyebrow">
          <span className={status === "live" ? "live-dot" : "small-dot"} />
          {listener ? "ZUHÖREN" : "SPRECHEN & VERBINDEN"}
          {status === "live" && (
            <span className="timer">
              {Math.floor(elapsed / 60)}:{String(elapsed % 60).padStart(2, "0")}
            </span>
          )}
        </div>
        <h1>
          {listener ? (
            <>
              Eine Sprache.
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
        <div className="language-row">
          <label>
            <span>Gesprochen</span>
            <div>
              <select
                aria-label="Gesprochene Sprache"
                value={source}
                disabled={!!room}
                onChange={(e) => setSource(e.target.value)}
              >
                {Object.entries(languages).map(([k, v]) => (
                  <option key={k} value={k}>
                    {v}
                  </option>
                ))}
              </select>
              <ChevronDown size={14} />
            </div>
          </label>
          <ArrowRight size={18} className="language-arrow" />
          <label>
            <span>Übersetzt</span>
            <div>
              <select
                aria-label="Zielsprache"
                value={language}
                disabled={!!room}
                onChange={(e) => setLanguage(e.target.value)}
              >
                {Object.entries(languages).map(([k, v]) => (
                  <option key={k} value={k}>
                    {v}
                  </option>
                ))}
              </select>
              <ChevronDown size={14} />
            </div>
          </label>
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
          <div className="controls">
            {!active && status !== "waiting" ? (
              <button className="primary" onClick={start}>
                {listener ? <Headphones size={19} /> : <Mic size={19} />}{" "}
                {listener
                  ? "Live zuhören"
                  : status === "ended"
                    ? "Weiter sprechen"
                    : "Sprechen starten"}{" "}
                <ArrowUpRight size={18} />
              </button>
            ) : (
              <button
                className="primary stop"
                disabled={status === "draining" || status === "connecting"}
                onClick={stop}
              >
                <Square size={15} fill="currentColor" />
                {status === "draining"
                  ? "Wird abgeschlossen …"
                  : listener
                    ? "Verlassen"
                    : "Sprechen beenden"}
              </button>
            )}
            {listener && (
              <button
                className="icon-button"
                onClick={toggleMute}
                aria-label={muted ? "Ton einschalten" : "Ton stummschalten"}
              >
                {muted ? <VolumeX size={20} /> : <Volume2 size={20} />}
              </button>
            )}
            {!listener && room && (
              <button
                className="icon-button"
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
          {listener && <details className="audio-check"><summary>Audio prüfen</summary><p>Audio-Pakete: {audioInfo.chunks} · Pegel: {audioInfo.peak}%<br/>Wiedergabe: {audioInfo.state} · {muted ? "stumm" : "Ton an"}</p><button className="icon-button" aria-label="Testton abspielen" onClick={testTone}><Volume2 size={18}/></button><p>{toneResult || "Testton abspielen"}</p></details>}
          {!listener && devices.length > 1 && (
            <select
              className="device"
              aria-label="Mikrofon"
              value={device}
              disabled={active}
              onChange={(e) => setDevice(e.target.value)}
            >
              <option value="">Standardmikrofon</option>
              {devices.map((d) => (
                <option key={d.deviceId} value={d.deviceId}>
                  {d.label || "Mikrofon"}
                </option>
              ))}
            </select>
          )}
        </section>
        {error && (
          <div className="alert" role="alert">
            {error}
          </div>
        )}
        {notice && <div className="notice">{notice}</div>}
        <section className={"transcripts " + (listener ? "single" : "")}>
          {!listener && (
            <article>
              <div className="card-label">
                <Mic size={15} /> DEINE WORTE <span>{languages[source]}</span>
              </div>
              <div className="transcript" aria-live="polite">
                {original || (
                  <span className="placeholder">
                    {transcription === "ready"
                      ? "Deine gesprochenen Worte erscheinen hier mit kurzer Verzögerung."
                      : "Die lokale Spracherkennung wird vorbereitet. Übersetzen ist bereits möglich."}
                  </span>
                )}
              </div>
            </article>
          )}
          <article>
            <div className="card-label">
              <AudioLines size={15} /> LIVE-ÜBERSETZUNG{" "}
              <span>{languages[language]}</span>
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
          </article>
        </section>
        {room && !listener && (
          <button className="invite" onClick={() => setShare(true)}>
            <span>
              <Radio size={19} />
              <span>
                Zuhörer einladen
                <small>Ein Link. Beliebige Geräte. Gemeinsam zuhören.</small>
              </span>
            </span>
            <ArrowUpRight size={19} />
          </button>
        )}
      </main>
      <footer>
        <span>Eine Stimme. Mehr Verständnis.</span>
        <span>Keine Anmeldung · Keine dauerhafte Aufzeichnung</span>
        <a href="/local-ca.cer">iPhone-Zertifikat</a>
      </footer>
      {share && (
        <div className="modal-backdrop" onClick={() => setShare(false)}>
          <section
            className="modal"
            role="dialog"
            aria-modal="true"
            aria-label="Sitzung teilen"
            onClick={(e) => e.stopPropagation()}
          >
            <button
              className="close icon-button"
              onClick={() => setShare(false)}
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
              <QRCodeSVG value={link} size={184} level="M" />
            </div>
            <input
              readOnly
              aria-label="Zuhörerlink"
              value={link}
              onFocus={(e) => e.target.select()}
            />
            <button className="primary" onClick={copy}>
              {copied ? <Check size={18} /> : <Link size={18} />}{" "}
              {copied ? "Link kopiert" : "Link kopieren"}
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
