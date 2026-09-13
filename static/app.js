// Omega — logique frontend : push-to-talk, pipeline STT -> chat -> TTS, cockpit.

const talkBtn = document.getElementById("talk-btn");
const talkBtnLabel = document.getElementById("talk-btn-label");
const statusDot = document.getElementById("status-dot");
const statusText = document.getElementById("status-text");
const lastUserEl = document.getElementById("last-user");
const lastHermesEl = document.getElementById("last-hermes");
const metricTelegram = document.getElementById("metric-telegram");
const metricQueue = document.getElementById("metric-queue");
const metricStt = document.getElementById("metric-stt");
const metricClaude = document.getElementById("metric-claude");
const metricOpenrouter = document.getElementById("metric-openrouter");
const ttsAudio = document.getElementById("tts-audio");

// Token anti-CSRF injecte par le backend dans index.html ; sans lui, /chat /stt /tts repondent 403.
const OMEGA_TOKEN = (document.querySelector('meta[name="omega-token"]') || {}).content || "";

function apiFetch(url, options = {}) {
  const headers = Object.assign({ "X-Omega-Token": OMEGA_TOKEN }, options.headers || {});
  return fetch(url, Object.assign({}, options, { headers }));
}

// Lit un JSON de reponse ; normalise toute erreur HTTP en { error: "..." }.
async function readJson(res) {
  let data;
  try {
    data = await res.json();
  } catch (err) {
    data = {};
  }
  if (!res.ok && !data.error) {
    data.error = data.detail ? JSON.stringify(data.detail) : `HTTP ${res.status}`;
  }
  return data;
}

const STATES = {
  idle: { label: "pret", dot: "" },
  listening: { label: "j'ecoute", dot: "listening" },
  transcribing: { label: "je transcris", dot: "busy" },
  thinking: { label: "en reflexion (Hermes)", dot: "busy" },
  speaking: { label: "je reponds", dot: "speaking" },
  error: { label: "erreur", dot: "error" },
};

let currentState = "idle";

function setState(name) {
  const s = STATES[name] || STATES.idle;
  currentState = STATES[name] ? name : "idle";
  statusText.textContent = s.label;
  statusDot.className = "dot" + (s.dot ? ` ${s.dot}` : "");
}

function showError(message) {
  lastHermesEl.textContent = message;
  setState("error");
}

// --- Enregistrement micro ------------------------------------------------------------------

let mediaRecorder = null;
let chunks = [];
let recording = false; // vrai des l'appui (meme pendant la demande de permission micro)
let recordSession = 0; // invalide un demarrage arrive apres un relachement

async function startRecording() {
  if (recording) return;
  recording = true;
  const session = ++recordSession;
  let stream;
  try {
    stream = await navigator.mediaDevices.getUserMedia({ audio: true });
  } catch (err) {
    recording = false;
    console.error(err);
    showError("micro inaccessible : " + (err.message || err));
    return;
  }
  if (!recording || session !== recordSession) {
    // Relache pendant la demande de permission : on ne laisse pas le micro ouvert.
    stream.getTracks().forEach((t) => t.stop());
    return;
  }
  stopTtsPlayback(); // barge-in : on coupe la reponse en cours (et le micro ne l'entend pas)
  chunks = [];
  mediaRecorder = new MediaRecorder(stream);
  mediaRecorder.ondataavailable = (e) => {
    if (e.data && e.data.size) chunks.push(e.data);
  };
  mediaRecorder.start();
  setState("listening");
  talkBtn.classList.add("recording");
  talkBtnLabel.textContent = "...";
}

// Idempotent : peut etre appele plusieurs fois (pointerup + lostpointercapture + blur...).
function stopRecording() {
  return new Promise((resolve) => {
    if (!recording) return resolve(null);
    recording = false;
    talkBtn.classList.remove("recording");
    talkBtnLabel.textContent = "Parler";
    const rec = mediaRecorder;
    mediaRecorder = null;
    if (!rec || rec.state === "inactive") {
      if (currentState === "listening") setState("idle");
      return resolve(null);
    }
    setState("transcribing");
    rec.onstop = () => {
      rec.stream.getTracks().forEach((t) => t.stop());
      resolve(new Blob(chunks, { type: rec.mimeType || "audio/webm" }));
    };
    try {
      rec.stop();
    } catch (err) {
      rec.stream.getTracks().forEach((t) => t.stop());
      setState("idle");
      resolve(null);
    }
  });
}

// --- Lecture TTS (streaming MediaSource si possible, sinon blob complet) -------------------

let currentObjectUrl = null;
let playback = null; // session de lecture en cours : { cancel() }

function stopTtsPlayback() {
  if (playback) {
    const p = playback;
    playback = null;
    p.cancel();
  }
  try {
    ttsAudio.pause();
  } catch (err) {
    /* ignore */
  }
}

function setAudioSource(url) {
  if (currentObjectUrl) URL.revokeObjectURL(currentObjectUrl);
  currentObjectUrl = url;
  ttsAudio.src = url;
}

function once(target, type) {
  return new Promise((resolve) => target.addEventListener(type, resolve, { once: true }));
}

function canStreamMp3() {
  return (
    typeof MediaSource !== "undefined" &&
    typeof MediaSource.isTypeSupported === "function" &&
    MediaSource.isTypeSupported("audio/mpeg")
  );
}

function appendChunk(sourceBuffer, chunk) {
  return new Promise((resolve, reject) => {
    const cleanup = () => {
      sourceBuffer.removeEventListener("updateend", onEnd);
      sourceBuffer.removeEventListener("error", onErr);
    };
    const onEnd = () => {
      cleanup();
      resolve();
    };
    const onErr = () => {
      cleanup();
      reject(new Error("SourceBuffer error"));
    };
    sourceBuffer.addEventListener("updateend", onEnd);
    sourceBuffer.addEventListener("error", onErr);
    try {
      sourceBuffer.appendBuffer(chunk);
    } catch (err) {
      cleanup();
      reject(err);
    }
  });
}

// Relaie le flux mp3 dans un MediaSource : la lecture demarre au 1er chunk recu,
// sans attendre la fin de la synthese.
async function streamIntoAudio(body, signal) {
  const mediaSource = new MediaSource();
  setAudioSource(URL.createObjectURL(mediaSource));
  await once(mediaSource, "sourceopen");
  const sourceBuffer = mediaSource.addSourceBuffer("audio/mpeg");
  const reader = body.getReader();
  let playPromise = null;
  try {
    while (true) {
      const { value, done } = await reader.read();
      if (done || signal.aborted || mediaSource.readyState !== "open") break;
      await appendChunk(sourceBuffer, value);
      if (!playPromise) {
        playPromise = ttsAudio.play();
        playPromise.catch(() => {}); // remonte plus bas, une fois le flux consomme
      }
    }
    if (mediaSource.readyState === "open") {
      if (sourceBuffer.updating) await once(sourceBuffer, "updateend");
      mediaSource.endOfStream();
    }
  } catch (err) {
    reader.cancel().catch(() => {});
    if (!signal.aborted && mediaSource.readyState === "open") {
      try {
        mediaSource.endOfStream("network");
      } catch (e) {
        /* ignore */
      }
    }
    throw err;
  }
  if (!playPromise) throw new Error("aucun audio recu");
  await playPromise; // un refus d'autoplay devient une erreur visible
}

// Synthetise et lit `text`. Resout a la fin de la lecture (ou si elle est interrompue),
// rejette si la synthese ou la lecture echoue.
async function speak(text) {
  stopTtsPlayback();
  const controller = new AbortController();
  let settle;
  const done = new Promise((resolve, reject) => {
    settle = { resolve, reject };
  });
  const onEnded = () => settle.resolve();
  const onError = () => settle.reject(new Error("lecture audio impossible"));
  ttsAudio.addEventListener("ended", onEnded);
  ttsAudio.addEventListener("error", onError);
  const session = {
    cancel() {
      controller.abort();
      settle.resolve();
    },
  };
  playback = session;
  try {
    const res = await apiFetch("/tts", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text }),
      signal: controller.signal,
    });
    if (!res.ok) {
      const data = await readJson(res);
      throw new Error(data.error || `TTS HTTP ${res.status}`);
    }
    if (canStreamMp3() && res.body) {
      await streamIntoAudio(res.body, controller.signal);
    } else {
      // Repli (navigateur sans MediaSource mp3) : tout telecharger puis lire.
      const blob = await res.blob();
      setAudioSource(URL.createObjectURL(blob));
      await ttsAudio.play();
    }
    await done;
  } catch (err) {
    if (!controller.signal.aborted) throw err; // sinon : interrompu volontairement
  } finally {
    ttsAudio.removeEventListener("ended", onEnded);
    ttsAudio.removeEventListener("error", onError);
    if (playback === session) playback = null;
  }
}

// --- Pipeline voix : STT -> chat (Hermes) -> TTS ------------------------------------------

async function pipeline(blob) {
  try {
    setState("transcribing");
    const form = new FormData();
    form.append("file", blob, "speech.webm");
    const sttRes = await apiFetch("/stt", { method: "POST", body: form });
    const sttData = await readJson(sttRes);
    if (sttData.error) {
      showError(sttData.error);
      return;
    }
    const text = (sttData.text || "").trim();
    lastUserEl.textContent = text || "(vide)";
    if (!text) {
      setState("idle");
      return;
    }

    setState("thinking");
    const chatRes = await apiFetch("/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text }),
    });
    const chatData = await readJson(chatRes);
    if (chatData.error) {
      showError(chatData.error);
      return;
    }

    const reply = chatData.reply || "";
    lastHermesEl.textContent = reply;
    if (!reply.trim()) {
      setState("idle");
      return;
    }

    setState("speaking");
    await speak(reply);
    if (currentState === "speaking") setState("idle"); // sauf si l'utilisateur a repris la parole
  } catch (err) {
    console.error(err);
    showError(err.message || String(err));
  }
}

// --- Push-to-talk (Pointer Events : souris, tactile, stylet) -------------------------------
// L'enregistrement s'arrete sur pointerup, mais aussi pointercancel / pointerleave /
// lostpointercapture / perte de focus : relacher hors du bouton ne laisse plus le micro
// ouvert avec l'UI figee sur « j'ecoute ».

function onPressStart(e) {
  if (e.button !== undefined && e.button !== 0) return; // bouton principal uniquement
  e.preventDefault();
  try {
    talkBtn.setPointerCapture(e.pointerId); // relacher n'importe ou termine l'enregistrement
  } catch (err) {
    /* ignore */
  }
  startRecording();
}

async function onPressEnd(e) {
  if (e && e.pointerId !== undefined && talkBtn.hasPointerCapture && talkBtn.hasPointerCapture(e.pointerId)) {
    try {
      talkBtn.releasePointerCapture(e.pointerId);
    } catch (err) {
      /* ignore */
    }
  }
  const blob = await stopRecording();
  if (blob && blob.size > 0) pipeline(blob);
  else if (blob) setState("idle");
}

talkBtn.addEventListener("pointerdown", onPressStart);
talkBtn.addEventListener("pointerup", onPressEnd);
talkBtn.addEventListener("pointercancel", onPressEnd);
talkBtn.addEventListener("pointerleave", onPressEnd);
talkBtn.addEventListener("lostpointercapture", onPressEnd);
talkBtn.addEventListener("contextmenu", (e) => e.preventDefault()); // appui long mobile
window.addEventListener("blur", () => onPressEnd());
document.addEventListener("visibilitychange", () => {
  if (document.hidden) onPressEnd();
});

// --- Cockpit -------------------------------------------------------------------------------

async function refreshStatus() {
  try {
    const res = await apiFetch("/status");
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();

    if (!data.telegram_configured) metricTelegram.textContent = "à configurer";
    else if (!data.hermes_target_configured) metricTelegram.textContent = "HERMES_TARGET manquant";
    else metricTelegram.textContent = "configuré";

    const pending = data.queue.pending_chat_requests;
    metricQueue.textContent = pending > 0 ? `${pending} en cours` : "inactif";

    const sttMetric = data.metrics.stt || {};
    metricStt.textContent = sttMetric.detail || "—";

    const claude = data.metrics.claude_code;
    metricClaude.textContent = claude.status === "ok" ? claude.detail : (claude.detail || "à configurer");

    const or = data.metrics.openrouter;
    metricOpenrouter.textContent =
      or.status === "ok" ? JSON.stringify(or.detail) : (or.detail || "à configurer");

    if (data.queue.last_exchange) {
      lastUserEl.textContent = data.queue.last_exchange.user;
      lastHermesEl.textContent = data.queue.last_exchange.hermes;
    }
  } catch (err) {
    metricTelegram.textContent = "indisponible";
  }
}

setState("idle");
refreshStatus();
setInterval(refreshStatus, 5000);

// Orbe violette animee (canvas), purement decoratif.
const canvas = document.getElementById("orb");
const ctx = canvas.getContext("2d");
let t = 0;
function drawOrb() {
  t += 0.02;
  const { width, height } = canvas;
  ctx.clearRect(0, 0, width, height);
  const cx = width / 2;
  const cy = height / 2;
  const baseR = 90;
  for (let i = 0; i < 3; i++) {
    const r = baseR + Math.sin(t + i) * 10 + i * 14;
    ctx.beginPath();
    ctx.arc(cx, cy, r, 0, Math.PI * 2);
    ctx.strokeStyle = `rgba(124, 58, 237, ${0.35 - i * 0.1})`;
    ctx.lineWidth = 2;
    ctx.stroke();
  }
  const gradient = ctx.createRadialGradient(cx, cy, 10, cx, cy, baseR);
  gradient.addColorStop(0, "rgba(167, 139, 250, 0.9)");
  gradient.addColorStop(1, "rgba(124, 58, 237, 0.05)");
  ctx.beginPath();
  ctx.arc(cx, cy, baseR - 20, 0, Math.PI * 2);
  ctx.fillStyle = gradient;
  ctx.fill();
  requestAnimationFrame(drawOrb);
}
drawOrb();
