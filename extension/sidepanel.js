import { API_BASE, WEB_BASE } from "./config.js";

const el = (id) => document.getElementById(id);
const notes = [];
const transcript = [];
const visuals = [];

let activeTabId = null;
let activeTabObj = null;
let capturing = false;

// Media Capture Variables
let currentStream = null;
let rawCaptureStream = null;
let isRecording = false;
const CHUNK_DURATION_MS = 2000;

// Voice Defense Variables
let isRecordingVoice = false;
let recognition = null;

function wireVisibilityToggle(inputEl, toggleEl) {
  toggleEl.addEventListener("click", () => {
    const showing = inputEl.type === "text";
    inputEl.type = showing ? "password" : "text";
    toggleEl.textContent = showing ? "Show" : "Hide";
  });
}
if (el("password") && el("toggleBtn")) {
  wireVisibilityToggle(el("password"), el("toggleBtn"));
}

async function checkAuth() {
  const auth = await chrome.runtime.sendMessage({ scope: "notecast", type: "GET_AUTH" });
  if (auth?.loggedIn) {
    showMain(auth.displayName || auth.email);
  } else {
    showAuth();
  }
}

function showAuth() {
  el("authView").classList.remove("hidden");
  el("mainView").classList.add("hidden");
  el("userBadge").classList.add("hidden");
}

async function showMain(displayName) {
  el("authView").classList.add("hidden");
  el("mainView").classList.remove("hidden");
  el("userBadge").classList.remove("hidden");
  el("userName").textContent = displayName || "";
  
  renderTranscript();
  renderNotes();
  renderVisuals();
  
  await detectVideo();
}

el("authForm").addEventListener("submit", async (e) => {
  e.preventDefault();
  const errorEl = el("authError");
  const loginBtn = el("loginBtn");
  errorEl.classList.add("hidden");
  loginBtn.disabled = true;
  loginBtn.textContent = "Signing in…";

  const result = await chrome.runtime.sendMessage({
    scope: "notecast",
    type: "LOGIN",
    email: el("email").value.trim(),
    password: el("password").value,
  });

  loginBtn.disabled = false;
  loginBtn.textContent = "Sign in";

  if (!result.ok) {
    errorEl.textContent = result.status === 429
      ? "Too many attempts — please wait a few minutes."
      : result.error;
    errorEl.classList.remove("hidden");
    return;
  }
  await showMain(result.displayName || result.email);
});

el("signupLink").addEventListener("click", (e) => {
  e.preventDefault();
  chrome.tabs.create({ url: `${WEB_BASE}/signup.html` });
});

el("forgotLink").addEventListener("click", (e) => {
  e.preventDefault();
  chrome.tabs.create({ url: `${WEB_BASE}/forgot-password.html` });
});

el("logoutBtn").addEventListener("click", async () => {
  await chrome.runtime.sendMessage({ scope: "notecast", type: "LOGOUT" });
  showAuth();
});

async function detectVideo() {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  if (!tab || !tab.url || !/youtube\.com\/watch/.test(tab.url)) {
    el("offSite").classList.remove("hidden");
    el("idleControls").classList.add("hidden");
    el("activeControls").classList.add("hidden");
    return;
  }
  
  activeTabId = tab.id;
  activeTabObj = tab; 
  el("offSite").classList.add("hidden");

  if (capturing) {
    el("idleControls").classList.add("hidden");
    el("activeControls").classList.remove("hidden");
    return;
  }

  let meta;
  try {
    meta = await chrome.tabs.sendMessage(tab.id, { scope: "notecast-meta", type: "GET_META" });
  } catch (err) {
    try {
      await chrome.scripting.executeScript({
        target: { tabId: tab.id },
        files: ["content.js"]
      });
      meta = await chrome.tabs.sendMessage(tab.id, { scope: "notecast-meta", type: "GET_META" });
    } catch (injectErr) {
      el("offSite").classList.remove("hidden");
      return;
    }
  }

  if (!meta || !meta.title) {
    el("offSite").classList.add("hidden");
    return;
  }

  el("videoTitle").textContent = meta.title;
  el("videoChannel").textContent = meta.channel;
  el("idleControls").dataset.meta = JSON.stringify(meta);
  el("idleControls").classList.remove("hidden");
}

chrome.tabs.onActivated.addListener(detectVideo);
chrome.tabs.onUpdated.addListener((tabId, changeInfo) => {
  if (changeInfo.url || changeInfo.status === "complete") {
    detectVideo();
  }
});

el("startBtn").addEventListener("click", async () => {
  const meta = JSON.parse(el("idleControls").dataset.meta || "{}");
  const startBtn = el("startBtn");
  startBtn.disabled = true;

  try {
    el("statusLabel").textContent = "Awaiting tab selection...";
    
    const streamId = await new Promise((resolve, reject) => {
      chrome.desktopCapture.chooseDesktopMedia(["tab", "audio"], (id) => {
        if (chrome.runtime.lastError) {
          reject(new Error(chrome.runtime.lastError.message));
        } else if (!id) {
          reject(new Error("Capture cancelled by user."));
        } else {
          resolve(id);
        }
      });
    });

    el("statusLabel").textContent = "Starting audio stream...";
    await startAudioCapture(streamId);

    capturing = true;
    el("idleControls").classList.add("hidden");
    el("activeControls").classList.remove("hidden");

    chrome.runtime.sendMessage({ 
      scope: "notecast", 
      type: "START_CAPTURE_PIPELINE", 
      payload: { tabId: activeTabId, videoMeta: meta }
    }).then(result => {
      if (!result || !result.ok) {
        stopAudioCapture(); 
        capturing = false;
        el("idleControls").classList.remove("hidden");
        el("activeControls").classList.add("hidden");
        alert(`Capture Failed: ${result?.error || "Unknown Error"}`);
      } else {
        el("statusLabel").textContent = "Connected (with latency)";
      }
    }).catch(e => console.warn(e));

  } catch (err) {
    capturing = false;
    el("idleControls").classList.remove("hidden");
    el("activeControls").classList.add("hidden");
    if (!err.message.includes("cancelled")) {
      alert(`Capture Error: ${err.message}. Ensure 'Also share tab audio' is checked!`);
    }
  } finally {
    startBtn.disabled = false;
  }
});

el("stopBtn").addEventListener("click", async () => {
  el("stopBtn").disabled = true;
  el("statusLabel").textContent = "Wrapping up…";
  stopAudioCapture(); 
  await chrome.runtime.sendMessage({ scope: "notecast", type: "STOP_CAPTURE" });
  el("stopBtn").disabled = false;
  el("activeControls").classList.add("hidden");
  el("finalizingNotice").classList.remove("hidden");
  capturing = false;
});

// AUDIO CAPTURE PIPELINE
async function startAudioCapture(streamId) {
  stopAudioCapture(); 

  let rawStream;
  try {
    rawStream = await navigator.mediaDevices.getUserMedia({
      audio: { mandatory: { chromeMediaSource: "desktop", chromeMediaSourceId: streamId } },
      video: { mandatory: { chromeMediaSource: "desktop", chromeMediaSourceId: streamId } }
    });
  } catch (err) {
    throw new Error(`Please ensure 'Also share tab audio' is checked.`);
  }

  const audioTracks = rawStream.getAudioTracks();
  if (audioTracks.length === 0) {
    rawStream.getTracks().forEach(t => t.stop());
    throw new Error("No audio tracks found.");
  }

  rawCaptureStream = rawStream;
  currentStream = new MediaStream(audioTracks);
  isRecording = true;
  recordStandaloneChunk();
}

function recordStandaloneChunk() {
  if (!isRecording || !currentStream || !currentStream.active) return;

  let recorder;
  try {
    recorder = new MediaRecorder(currentStream, { mimeType: "audio/webm;codecs=opus" });
  } catch (e) {
    recorder = new MediaRecorder(currentStream);
  }

  const chunks = [];
  recorder.ondataavailable = (event) => {
    if (event.data && event.data.size > 0) chunks.push(event.data);
  };

  recorder.onstop = () => {
    if (chunks.length > 0 && isRecording) {
      const blob = new Blob(chunks, { type: "audio/webm" });
      const reader = new FileReader();
      reader.onloadend = () => {
        const base64data = reader.result.split(",")[1];
        if (base64data) {
          chrome.runtime.sendMessage({
            scope: "notecast",
            type: "AUDIO_CHUNK",
            seq: Date.now(),
            data_b64: base64data,
            duration_ms: CHUNK_DURATION_MS,
          }).catch(() => {});
        }
      };
      reader.readAsDataURL(blob);
    }
    if (isRecording) setTimeout(recordStandaloneChunk, 50);
  };

  recorder.start();
  setTimeout(() => {
    if (recorder && recorder.state === "recording") recorder.stop();
  }, CHUNK_DURATION_MS);
}

function stopAudioCapture() {
  isRecording = false;
  if (currentStream) { currentStream.getTracks().forEach((t) => t.stop()); currentStream = null; }
  if (rawCaptureStream) { rawCaptureStream.getTracks().forEach((t) => t.stop()); rawCaptureStream = null; }
}

// SOCRATIC FEYNMAN VOICE HANDLER
el("micBtn").addEventListener("click", () => {
  if (isRecordingVoice) stopVoiceDefense();
  else startVoiceDefense();
});

function startVoiceDefense() {
  const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (!SpeechRecognition) {
    alert("Speech recognition is not supported in this browser.");
    return;
  }

  recognition = new SpeechRecognition();
  recognition.lang = "en-US";
  recognition.continuous = false;
  recognition.interimResults = false;

  recognition.onstart = () => {
    isRecordingVoice = true;
    el("micBtn").classList.add("recording");
    el("micStatus").textContent = "Listening... Speak your explanation out loud.";
  };

  recognition.onresult = async (event) => {
    const userSpeech = event.results[0][0].transcript;
    el("micStatus").textContent = "Evaluating with Socratic AI...";
    
    try {
      const auth = await chrome.runtime.sendMessage({ scope: "notecast", type: "GET_AUTH" });
      const resp = await fetch(`${API_BASE}/socratic/evaluate`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "Authorization": `Bearer ${auth.token}`
        },
        body: JSON.stringify({
          concept: el("conceptSelect").value,
          user_explanation: userSpeech,
          context_notes: notes.map(n => n.body_md).join("\n")
        })
      });

      const data = await resp.json();
      el("socraticResult").classList.remove("hidden");
      el("socraticScore").textContent = `Score: ${data.score}/100`;
      el("socraticBody").textContent = data.feedback;
      el("socraticQuestion").textContent = `💡 Socratic Question: ${data.socratic_question}`;
      el("micStatus").textContent = "Click mic to record another attempt.";
    } catch(e) {
      el("micStatus").textContent = "Evaluation failed. Please try again.";
    }
  };

  recognition.onend = () => stopVoiceDefense();
  recognition.onerror = () => stopVoiceDefense();

  recognition.start();
}

function stopVoiceDefense() {
  isRecordingVoice = false;
  el("micBtn").classList.remove("recording");
  if (recognition) recognition.stop();
}

// UI RENDERING
chrome.runtime.onMessage.addListener((message) => {
  if (message.scope !== "notecast") return;
  switch (message.type) {
    case "transcript":
    case "transcript_segment":
      if (message.segment) transcript.push(message.segment);
      else if (message.text) transcript.push({ start_ms: message.start_ms || 0, text: message.text });
      renderTranscript();
      break;
    case "note":
      upsertNote(message.section);
      renderNotes();
      break;
    case "visual":
      visuals.push(message.event);
      renderVisuals();
      break;
    case "session_started":
      el("statusLabel").textContent = "Capturing...";
      break;
  }
});

function upsertNote(section) {
  const idx = notes.findIndex((n) => n.id === section.id);
  if (idx >= 0) notes[idx] = section;
  else notes.push(section);
}

function renderNotes() {
  const panel = el("panel-notes");
  if (!panel) return;
  if (!notes.length) {
    panel.innerHTML = `<div class="empty-state">Notes will appear here roughly every 30 seconds as the video plays.</div>`;
    return;
  }
  panel.innerHTML = notes
    .map(
      (n) => `<div class="note-card">
        <div class="note-heading">${escapeHtml(n.heading)}</div>
        <div class="note-body">${escapeHtml(n.body_md)}</div>
      </div>`
    )
    .join("");
}

function renderTranscript() {
  const panel = el("panel-transcript");
  if (!panel) return;
  if (transcript.length === 0) {
    panel.innerHTML = `<div class="empty-state">Live captions will appear here once audio is detected...</div>`;
    return;
  }
  panel.innerHTML = transcript
    .map(
      (s) => `<div class="transcript-line"><span class="transcript-ts">[${msToClock(s.start_ms)}]</span>${escapeHtml(s.text)}</div>`
    )
    .join("");
  panel.scrollTop = panel.scrollHeight;
}

function renderVisuals() {
  const panel = el("panel-visuals");
  if (!panel) return;
  if (!visuals.length) {
    panel.innerHTML = `<div class="empty-state">Diagrams, slides and code shown in the video will be captured here.</div>`;
    return;
  }
  panel.innerHTML = visuals
    .map(
      (v) => `<div class="visual-card">
        ${v.storage_key ? `<img src="${API_BASE}${v.storage_key}" class="visual-img" />` : ""}
        <span class="visual-type">${escapeHtml(v.type)}</span>
        <div class="visual-desc">${escapeHtml(v.description)}</div>
      </div>`
    )
    .join("");
}

document.querySelectorAll(".tab").forEach((tab) => {
  tab.addEventListener("click", () => {
    document.querySelectorAll(".tab").forEach((t) => t.classList.remove("active"));
    tab.classList.add("active");
    document.querySelectorAll(".panel").forEach((p) => p.classList.add("hidden"));
    el(`panel-${tab.dataset.tab}`).classList.remove("hidden");
  });
});

function msToClock(ms) {
  const s = Math.floor(ms / 1000);
  const m = Math.floor(s / 60);
  const ss = String(s % 60).padStart(2, "0");
  return `${m}:${ss}`;
}

function escapeHtml(str) {
  return (str || "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

checkAuth();