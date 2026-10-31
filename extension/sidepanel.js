import { API_BASE, WEB_BASE } from "./config.js";

const el = (id) => document.getElementById(id);
const notes = [];
const transcript = [];
const visuals = [];

let activeTabId = null;
let activeTabObj = null;
let capturing = false;
let isAdActive = false;

let currentStream = null;
let rawCaptureStream = null;
let isRecording = false;
const CHUNK_DURATION_MS = 5000; 

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
  if (el("authView")) el("authView").classList.remove("hidden");
  if (el("mainView")) el("mainView").classList.add("hidden");
  if (el("userBadge")) el("userBadge").classList.add("hidden");
}

async function showMain(displayName) {
  if (el("authView")) el("authView").classList.add("hidden");
  if (el("mainView")) el("mainView").classList.remove("hidden");
  if (el("userBadge")) el("userBadge").classList.remove("hidden");
  if (el("userName")) el("userName").textContent = displayName || "";
  
  renderTranscript();
  renderNotes();
  renderVisuals();
  
  await detectVideo();
}

if (el("authForm")) {
  el("authForm").addEventListener("submit", async (e) => {
    e.preventDefault();
    const errorEl = el("authError");
    const loginBtn = el("loginBtn");
    if (errorEl) errorEl.classList.add("hidden");
    if (loginBtn) {
      loginBtn.disabled = true;
      loginBtn.textContent = "Signing in…";
    }

    const result = await chrome.runtime.sendMessage({
      scope: "notecast",
      type: "LOGIN",
      email: el("email").value.trim(),
      password: el("password").value,
    });

    if (loginBtn) {
      loginBtn.disabled = false;
      loginBtn.textContent = "Sign in";
    }

    if (!result.ok) {
      if (errorEl) {
        errorEl.textContent = result.status === 429
          ? "Too many attempts — please wait a few minutes."
          : result.error;
        errorEl.classList.remove("hidden");
      }
      return;
    }
    await showMain(result.displayName || result.email);
  });
}

if (el("signupLink")) {
  el("signupLink").addEventListener("click", (e) => {
    e.preventDefault();
    chrome.tabs.create({ url: `${WEB_BASE}/signup.html` });
  });
}

if (el("forgotLink")) {
  el("forgotLink").addEventListener("click", (e) => {
    e.preventDefault();
    chrome.tabs.create({ url: `${WEB_BASE}/forgot-password.html` });
  });
}

if (el("logoutBtn")) {
  el("logoutBtn").addEventListener("click", async () => {
    await chrome.runtime.sendMessage({ scope: "notecast", type: "LOGOUT" });
    showAuth();
  });
}

async function detectVideo() {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  if (!tab || !tab.url || !/youtube\.com\/watch/.test(tab.url)) {
    if (el("offSite")) el("offSite").classList.remove("hidden");
    if (el("idleControls")) el("idleControls").classList.add("hidden");
    if (el("activeControls")) el("activeControls").classList.add("hidden");
    return;
  }
  
  activeTabId = tab.id;
  activeTabObj = tab; 
  if (el("offSite")) el("offSite").classList.add("hidden");

  if (capturing) {
    if (el("idleControls")) el("idleControls").classList.add("hidden");
    if (el("activeControls")) el("activeControls").classList.remove("hidden");
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
      if (el("offSite")) el("offSite").classList.remove("hidden");
      return;
    }
  }

  if (!meta || !meta.title) {
    if (el("offSite")) el("offSite").classList.add("hidden");
    return;
  }

  if (el("videoTitle")) el("videoTitle").textContent = meta.title;
  if (el("videoChannel")) el("videoChannel").textContent = meta.channel;
  if (el("idleControls")) {
    el("idleControls").dataset.meta = JSON.stringify(meta);
    el("idleControls").classList.remove("hidden");
  }
}

chrome.tabs.onActivated.addListener(detectVideo);
chrome.tabs.onUpdated.addListener((tabId, changeInfo) => {
  if (changeInfo.url || changeInfo.status === "complete") {
    detectVideo();
  }
});

// START CAPTURING
if (el("startBtn")) {
  el("startBtn").addEventListener("click", async () => {
    const meta = JSON.parse(el("idleControls")?.dataset?.meta || "{}");
    const startBtn = el("startBtn");
    startBtn.disabled = true;

    try {
      if (el("statusLabel")) el("statusLabel").textContent = "Awaiting tab selection...";
      
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

      if (el("statusLabel")) el("statusLabel").textContent = "Starting audio stream...";
      await startAudioCapture(streamId);

      capturing = true;
      if (el("idleControls")) el("idleControls").classList.add("hidden");
      if (el("activeControls")) el("activeControls").classList.remove("hidden");

      chrome.runtime.sendMessage({ 
        scope: "notecast", 
        type: "START_CAPTURE_PIPELINE", 
        payload: { tabId: activeTabId, videoMeta: meta }
      }).then(result => {
        if (!result || !result.ok) {
          stopAudioCapture(); 
          capturing = false;
          if (el("idleControls")) el("idleControls").classList.remove("hidden");
          if (el("activeControls")) el("activeControls").classList.add("hidden");
          alert(`Capture Failed: ${result?.error || "Unknown Error"}`);
        } else {
          if (el("statusLabel")) el("statusLabel").textContent = "Connected (with latency)";
        }
      }).catch(e => console.warn(e));

    } catch (err) {
      capturing = false;
      if (el("idleControls")) el("idleControls").classList.remove("hidden");
      if (el("activeControls")) el("activeControls").classList.add("hidden");
      if (!err.message.includes("cancelled")) {
        alert(`Capture Error: ${err.message}. Ensure 'Also share tab audio' is checked!`);
      }
    } finally {
      startBtn.disabled = false;
    }
  });
}

// FINALIZE CAPTURING
if (el("stopBtn")) {
  el("stopBtn").addEventListener("click", async () => {
    el("stopBtn").disabled = true;
    if (el("statusLabel")) el("statusLabel").textContent = "Wrapping up…";
    
    stopAudioCapture(); 
    await chrome.runtime.sendMessage({ scope: "notecast", type: "STOP_CAPTURE" });
    
    el("stopBtn").disabled = false;
    if (el("activeControls")) el("activeControls").classList.add("hidden");
    if (el("finalizingNotice")) el("finalizingNotice").classList.remove("hidden");
    capturing = false;
  });
}

// START ANOTHER NOTE FROM ACTIVE CONTROLS
if (el("startAnotherActiveBtn")) {
  el("startAnotherActiveBtn").addEventListener("click", async () => {
    stopAudioCapture(); 
    await chrome.runtime.sendMessage({ scope: "notecast", type: "STOP_CAPTURE" });
    
    capturing = false;
    notes.length = 0;
    transcript.length = 0;
    visuals.length = 0;
    
    renderNotes();
    renderTranscript();
    renderVisuals();
    
    if (el("activeControls")) el("activeControls").classList.add("hidden");
    if (el("finalizingNotice")) el("finalizingNotice").classList.add("hidden");
    
    detectVideo();
  });
}

// RESET EXTENSION STATE FOR NEW VIDEO
if (el("resetBtn")) {
  el("resetBtn").addEventListener("click", () => {
    capturing = false;
    notes.length = 0;
    transcript.length = 0;
    visuals.length = 0;
    
    renderNotes();
    renderTranscript();
    renderVisuals();
    
    if (el("finalizingNotice")) el("finalizingNotice").classList.add("hidden");
    detectVideo(); 
  });
}

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
    if (chunks.length > 0 && isRecording && !isAdActive) {
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
    
    if (isRecording) {
      recordStandaloneChunk(); 
    }
  };

  recorder.start();
  
  setTimeout(() => {
    if (recorder && recorder.state === "recording") {
      recorder.stop();
    }
  }, CHUNK_DURATION_MS);
}

function stopAudioCapture() {
  isRecording = false;
  if (currentStream) { currentStream.getTracks().forEach((t) => t.stop()); currentStream = null; }
  if (rawCaptureStream) { rawCaptureStream.getTracks().forEach((t) => t.stop()); rawCaptureStream = null; }
}

// SOCRATIC FEYNMAN VOICE HANDLER
if (el("micBtn")) {
  el("micBtn").addEventListener("click", () => {
    if (isRecordingVoice) stopVoiceDefense();
    else startVoiceDefense();
  });
}

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
    if (el("micBtn")) el("micBtn").classList.add("recording");
    if (el("micStatus")) el("micStatus").textContent = "Listening... Speak your explanation out loud.";
  };

  recognition.onresult = async (event) => {
    const userSpeech = event.results[0][0].transcript;
    if (el("micStatus")) el("micStatus").textContent = "Evaluating with Socratic AI...";
    
    try {
      const auth = await chrome.runtime.sendMessage({ scope: "notecast", type: "GET_AUTH" });
      const resp = await fetch(`${API_BASE}/socratic/evaluate`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "Authorization": `Bearer ${auth.token}`
        },
        body: JSON.stringify({
          concept: el("conceptSelect") ? el("conceptSelect").value : "General Concept",
          user_explanation: userSpeech,
          context_notes: notes.map(n => n.body_md).join("\n")
        })
      });

      const data = await resp.json();
      
      const score = data.score ?? data.evaluation?.score ?? data.overall_score ?? "--";
      const feedback = data.feedback ?? data.evaluation?.feedback ?? data.analysis ?? "No feedback generated.";
      const question = data.socratic_question ?? data.evaluation?.socratic_question ?? data.question ?? "";

      if (el("socraticResult")) el("socraticResult").classList.remove("hidden");
      if (el("socraticScore")) el("socraticScore").textContent = `Score: ${score}/100`;
      if (el("socraticBody")) el("socraticBody").textContent = feedback;
      if (el("socraticQuestion")) el("socraticQuestion").textContent = question ? `💡 Socratic Question: ${question}` : "";
      if (el("micStatus")) el("micStatus").textContent = "Click mic to record another attempt.";
    } catch(e) {
      if (el("micStatus")) el("micStatus").textContent = "Evaluation failed. Please try again.";
    }
  };

  recognition.onend = () => stopVoiceDefense();
  recognition.onerror = () => stopVoiceDefense();

  recognition.start();
}

function stopVoiceDefense() {
  isRecordingVoice = false;
  if (el("micBtn")) el("micBtn").classList.remove("recording");
  if (recognition) recognition.stop();
}

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
      if (message.section) {
        upsertNote(message.section);
        renderNotes();
      }
      break;
    case "visual":
      if (message.event) {
        visuals.push(message.event);
        renderVisuals();
      }
      break;
    case "session_started":
      if (el("statusLabel")) el("statusLabel").textContent = "Capturing...";
      break;
    case "AD_STATUS_CHANGE":
      isAdActive = message.isAd;
      if (el("statusLabel")) {
        if (isAdActive) {
          el("statusLabel").textContent = "⏸️ Ad playing (Paused)";
          el("statusLabel").style.color = "#f59e0b";
        } else {
          el("statusLabel").textContent = "Capturing...";
          el("statusLabel").style.color = "#10b981";
        }
      }
      break;
  }
});

function upsertNote(section) {
  const idx = notes.findIndex((n) => n.id === section.id);
  if (idx >= 0) notes[idx] = section;
  else notes.push(section);
}

function buildImageUrl(storageKey) {
  if (!storageKey) return "";
  if (storageKey.startsWith("http://") || storageKey.startsWith("https://")) return storageKey;
  const cleanKey = storageKey.startsWith("/") ? storageKey : `/${storageKey}`;
  return `${API_BASE}${cleanKey}`;
}

function renderNotes() {
  const panel = el("notesContainer");
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
  const panel = el("transcriptContainer");
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
  const panel = el("capturesContainer");
  if (!panel) return;
  if (!visuals.length) {
    panel.innerHTML = `<div class="empty-state">Diagrams, slides and code shown in the video will be captured here.</div>`;
    return;
  }
  panel.innerHTML = visuals
    .map(
      (v) => `<div class="visual-card">
        ${v.storage_key ? `<img src="${buildImageUrl(v.storage_key)}" class="visual-img" alt="Captured visual" onerror="this.style.display='none'" />` : ""}
        <span class="visual-type">${escapeHtml(v.type || "slide")}</span>
        <div class="visual-desc">${escapeHtml(v.description || "")}</div>
      </div>`
    )
    .join("");
}

document.querySelectorAll(".tab").forEach((tab) => {
  tab.addEventListener("click", () => {
    document.querySelectorAll(".tab").forEach((t) => t.classList.remove("active"));
    tab.classList.add("active");
    document.querySelectorAll(".panel").forEach((p) => p.classList.add("hidden"));
    if (el(`panel-${tab.dataset.tab}`)) {
      el(`panel-${tab.dataset.tab}`).classList.remove("hidden");
    }
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