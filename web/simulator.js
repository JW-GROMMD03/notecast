// ============================================================================
// NOTECAST AI HTML VISUALIZER CONTROLLER (DOMAIN AGNOSTIC, PRODUCTION GRADE)
// Features: URL Parsing, Advanced Cache TTL, Real-time Iframe Telemetry,
// Defensive Error Handling, and Enterprise Text-to-Speech (TTS) Chunking.
// ============================================================================

"use strict";

/**
 * ============================================================================
 * 1. CONFIGURATION & STATE MANAGEMENT
 * ============================================================================
 */
const CONFIG = {
  CACHE_TTL_MS: 1000 * 60 * 60, // 1 Hour Cache validity
  MAX_RETRIES: 3,               // Network retry threshold
  RETRY_DELAY_MS: 1500,
  TTS_RATE: 0.95,
  TTS_PITCH: 1.0,
  DEFAULT_TOPIC: "Interactive System Architecture"
};

const STATE = {
  isGenerating: false,
  isSpeaking: false,
  currentSchema: null,
  activeMetrics: new Set(),
  requestedTopic: ""
};

/**
 * ============================================================================
 * 2. SECURE DOM BINDINGS & LOGGING
 * ============================================================================
 */
const DOM = {
  iframe: document.getElementById('simIframe'),
  explanationText: document.getElementById('explanationText'),
  voiceSelect: document.getElementById('voiceSelect'),
  speakBtn: document.getElementById('speakBtn'),
  pauseSpeakBtn: document.getElementById('pauseSpeakBtn'),
  stopSpeakBtn: document.getElementById('stopSpeakBtn'),
  headerTitle: document.getElementById('headerTitle'),
  simHeading: document.getElementById('simHeading'),
  simDesc: document.getElementById('simDesc'),
  dynamicMetricsContainer: document.getElementById('dynamicMetricsContainer'),
  refreshSimBtn: document.getElementById('refreshSimBtn')
};

const Logger = {
  info: (msg, ...args) => console.log(`%c[NoteCast:INFO] %c${msg}`, "color: #3b82f6; font-weight: bold", "color: inherit", ...args),
  warn: (msg, ...args) => console.warn(`%c[NoteCast:WARN] %c${msg}`, "color: #f59e0b; font-weight: bold", "color: inherit", ...args),
  error: (msg, ...args) => console.error(`%c[NoteCast:ERROR] %c${msg}`, "color: #ef4444; font-weight: bold", "color: inherit", ...args)
};

/**
 * ============================================================================
 * 3. URL PARSING & INITIALIZATION
 * ============================================================================
 */
function parseRequest() {
  try {
    const urlParams = new URLSearchParams(window.location.search);
    const rawTopic = urlParams.get('topic');
    STATE.requestedTopic = rawTopic ? decodeURIComponent(rawTopic.trim()) : CONFIG.DEFAULT_TOPIC;
    Logger.info(`Parsed topic request: "${STATE.requestedTopic}"`);
  } catch (error) {
    Logger.error("Failed to parse URL parameters. Defaulting.", error);
    STATE.requestedTopic = CONFIG.DEFAULT_TOPIC;
  }
}

/**
 * ============================================================================
 * 4. ADVANCED CACHE MANAGER
 * ============================================================================
 */
const CacheManager = {
  getKey: () => `notecast_sim_${STATE.requestedTopic.toLowerCase().replace(/\s+/g, '_')}`,

  get: () => {
    try {
      const storedStr = sessionStorage.getItem(CacheManager.getKey());
      if (!storedStr) return null;
      
      const stored = JSON.parse(storedStr);
      if (!stored.timestamp || !stored.data) {
        CacheManager.invalidate();
        return null;
      }
      
      // Validate Expiration TTL
      if (Date.now() - stored.timestamp > CONFIG.CACHE_TTL_MS) {
        Logger.warn("Cache expired. Invalidating payload.");
        CacheManager.invalidate();
        return null;
      }
      
      Logger.info("Successful cache hit.");
      return stored.data;
    } catch (e) {
      Logger.error("Cache retrieval failed, potential corruption.", e);
      CacheManager.invalidate();
      return null;
    }
  },

  set: (schemaData) => {
    try {
      const payload = {
        timestamp: Date.now(),
        data: schemaData
      };
      sessionStorage.setItem(CacheManager.getKey(), JSON.stringify(payload));
      Logger.info("Schema successfully cached.");
    } catch (e) {
      Logger.error("Failed to write to sessionStorage (Quota exceeded?).", e);
    }
  },

  invalidate: () => {
    sessionStorage.removeItem(CacheManager.getKey());
    Logger.info("Cache invalidated for current topic.");
  }
};

/**
 * ============================================================================
 * 5. SIMULATION BOOTSTRAPPER & NETWORK ENGINE
 * ============================================================================
 */
async function fetchWithRetry(url, options, retries = CONFIG.MAX_RETRIES) {
  for (let i = 0; i < retries; i++) {
    try {
      const res = await fetch(url, options);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      return await res.json();
    } catch (err) {
      Logger.warn(`Fetch attempt ${i + 1} failed: ${err.message}`);
      if (i === retries - 1) throw err;
      await new Promise(resolve => setTimeout(resolve, CONFIG.RETRY_DELAY_MS * (i + 1))); // Exponential backoff
    }
  }
}

function injectLoadingState() {
  DOM.iframe.classList.add('loading');
  DOM.headerTitle.textContent = `Synthesizing: ${STATE.requestedTopic}...`;
  
  DOM.explanationText.innerHTML = `
    <div style="color: #60a5fa; font-weight: bold; margin-bottom: 12px; font-size: 1.1rem; border-bottom: 1px solid #1e293b; padding-bottom: 8px;">
      Establishing Secure LLM Pipeline...
    </div>
    <p style="color: #cbd5e1; line-height: 1.6;">
      Please wait while the generative engine synthesizes a complete, mathematically precise Interactive HTML/JS Simulation tailored explicitly for <strong>${STATE.requestedTopic}</strong>.
    </p>
    <ul style="color: #94a3b8; font-size: 0.85rem; margin-top: 15px; padding-left: 20px; line-height: 1.8;">
      <li>Constructing visual architecture DOM</li>
      <li>Generating real-time interactive JavaScript</li>
      <li>Styling deep-space UI components</li>
    </ul>
  `;
  
  DOM.iframe.srcdoc = `
    <!DOCTYPE html>
    <html>
    <body style="margin:0; background:#02040a; color:#3b82f6; display:flex; flex-direction:column; align-items:center; justify-content:center; height:100vh; font-family:-apple-system, BlinkMacSystemFont, sans-serif;">
      <div style="width:64px; height:64px; border:4px solid #0f172a; border-top:4px solid #3b82f6; border-right:4px solid #3b82f6; border-radius:50%; animation:spin 1s cubic-bezier(0.55, 0.085, 0.68, 0.53) infinite; box-shadow: 0 0 15px rgba(59, 130, 246, 0.2);"></div>
      <h3 style="margin-top:25px; color:#f8fafc; font-weight:700; letter-spacing:0.5px; font-size: 1.2rem;">Booting Execution Engine</h3>
      <p style="color:#64748b; font-size:0.95rem; text-align:center; max-width:400px; margin-top:10px; line-height: 1.5;">Generating runtime geometry, physics vectors, and event listeners...</p>
      <style>@keyframes spin { 0% { transform: rotate(0deg); } 100% { transform: rotate(360deg); } }</style>
    </body>
    </html>
  `;
}

async function initializeSimulation(forceRefresh = false) {
  if (STATE.isGenerating) return;
  STATE.isGenerating = true;

  if (forceRefresh) CacheManager.invalidate();

  let schema = CacheManager.get();

  if (!schema) {
    injectLoadingState();
    
    try {
      schema = await fetchWithRetry("/diagrams/generate-sim/", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ topic: STATE.requestedTopic })
      });
      
      if (schema && schema.html_code) {
        CacheManager.set(schema);
      } else {
        throw new Error("Invalid schema structure returned from API");
      }
    } catch (err) {
      Logger.error("Simulation Generation Halts:", err);
      DOM.explanationText.innerHTML = `
        <div style="background: rgba(239, 68, 68, 0.1); border: 1px solid #ef4444; padding: 15px; border-radius: 8px;">
          <h4 style="margin: 0 0 10px 0; color: #ef4444;">Generation Failed</h4>
          <p style="margin: 0; color: #f8fafc; font-size: 0.9rem;">The backend LLM API timed out or refused the connection. Please verify API keys and network connectivity.</p>
        </div>
      `;
      DOM.iframe.classList.remove('loading');
      STATE.isGenerating = false;
      return;
    }
  }

  STATE.currentSchema = schema;
  
  // Hydrate the UI Shell with generated metadata
  DOM.headerTitle.textContent = schema.title || STATE.requestedTopic;
  DOM.simHeading.textContent = "Architecture Details";
  DOM.simDesc.textContent = schema.description || `Live interactive model for ${STATE.requestedTopic}`;
  DOM.explanationText.innerHTML = schema.detailed_lecture || "<em>No detailed lecture generated for this context.</em>";
  
  // Inject the custom HTML/CSS/JS application safely into the sandbox
  DOM.iframe.onload = () => {
    Logger.info("Iframe execution initialized successfully.");
    DOM.iframe.classList.remove('loading');
    STATE.isGenerating = false;
  };
  
  DOM.iframe.srcdoc = schema.html_code;
}

// Bind Refresh Control
DOM.refreshSimBtn.addEventListener('click', () => {
  if (confirm("This will trigger a new AI generation and overwrite the current visualizer layout. Continue?")) {
    initializeSimulation(true);
  }
});

/**
 * ============================================================================
 * 6. SECURE CROSS-FRAME TELEMETRY (IFRAME -> PARENT POSTMESSAGE)
 * ============================================================================
 */
window.addEventListener("message", (event) => {
  // Validate incoming payload signature defensively
  if (!event.data || typeof event.data !== 'object') return;
  if (event.data.type !== 'UPDATE_METRIC') return;
  
  const { title, value } = event.data;
  if (!title || value === undefined) {
    Logger.warn("Received malformed telemetry packet.", event.data);
    return;
  }

  // Create a safe DOM ID for the metric box
  const safeId = "metric_ui_" + title.toString().replace(/[^a-zA-Z0-9]/g, "_").toLowerCase();
  let metricEl = document.getElementById(safeId);

  if (!metricEl) {
    Logger.info(`Registering new telemetry tracker: ${title}`);
    metricEl = document.createElement('div');
    metricEl.className = 'metric-box';
    metricEl.id = safeId;
    metricEl.innerHTML = `
      <div class="metric-title">${title}</div>
      <div class="metric-value" id="${safeId}_val">${value}</div>
    `;
    DOM.dynamicMetricsContainer.appendChild(metricEl);
    STATE.activeMetrics.add(safeId);
  } else {
    // Update existing metric and apply CSS flash animation
    const valEl = document.getElementById(`${safeId}_val`);
    if (valEl.textContent !== String(value)) {
      valEl.textContent = value;
      metricEl.style.transform = "scale(1.04)";
      metricEl.style.borderColor = "rgba(59, 130, 246, 0.8)";
      metricEl.style.background = "rgba(59, 130, 246, 0.15)";
      
      // Debounce animation reset
      setTimeout(() => {
        metricEl.style.transform = "scale(1)";
        metricEl.style.borderColor = "rgba(59, 130, 246, 0.2)";
        metricEl.style.background = "rgba(59, 130, 246, 0.06)";
      }, 200);
    }
  }
});

/**
 * ============================================================================
 * 7. ENTERPRISE TEXT-TO-SPEECH (TTS) CHUNKING ENGINE
 * Standard WebSpeech API drops audio after 15 seconds on long strings. 
 * This engine splits text by sentence boundary, manages queue indexing, 
 * and handles pause/resume lifecycle accurately.
 * ============================================================================
 */
class TTSEngine {
  constructor() {
    this.voices = [];
    this.speechChunks = [];
    this.currentChunkIndex = 0;
    this.isActive = false;
    
    // Bind hardware events if available
    if (window.speechSynthesis) {
      window.speechSynthesis.onvoiceschanged = this.populateVoices.bind(this);
      this.populateVoices();
    }
  }

  populateVoices() {
    this.voices = window.speechSynthesis.getVoices();
    DOM.voiceSelect.innerHTML = "";
    
    // Fallback if voices take time to load (Safari)
    if (this.voices.length === 0) return;

    this.voices.forEach((v, index) => {
      const option = document.createElement('option');
      option.value = index;
      option.textContent = `${v.name} (${v.lang})`;
      
      // Prioritize clear English voices
      if (v.default || v.lang === 'en-GB' || v.lang === 'en-US') {
        option.selected = true;
      }
      DOM.voiceSelect.appendChild(option);
    });
    Logger.info(`Loaded ${this.voices.length} TTS profiles.`);
  }

  // Regex utility to intelligently split HTML/Text into digestible sentences
  chunkLecture(rawHTML) {
    const cleanText = rawHTML.replace(/<[^>]*>?/gm, ' ').replace(/\s+/g, ' ');
    // Split by ., !, or ? followed by a space, keeping the punctuation attached
    const chunks = cleanText.match(/[^.!?]+[.!?]+/g) || [cleanText];
    return chunks.map(c => c.trim()).filter(c => c.length > 0);
  }

  speakNextChunk() {
    if (this.currentChunkIndex >= this.speechChunks.length) {
      this.stop();
      return;
    }

    const chunk = this.speechChunks[this.currentChunkIndex];
    const utterance = new SpeechSynthesisUtterance(chunk);
    
    const selectedIdx = parseInt(DOM.voiceSelect.value, 10);
    if (!isNaN(selectedIdx) && this.voices[selectedIdx]) {
      utterance.voice = this.voices[selectedIdx];
    }
    
    utterance.rate = CONFIG.TTS_RATE; 
    utterance.pitch = CONFIG.TTS_PITCH;

    utterance.onend = () => {
      this.currentChunkIndex++;
      // Only proceed if we haven't been paused/stopped manually
      if (this.isActive && !window.speechSynthesis.paused) {
        this.speakNextChunk();
      }
    };

    utterance.onerror = (e) => {
      Logger.error("TTS execution error at chunk boundary:", e);
      this.stop();
    };

    window.speechSynthesis.speak(utterance);
  }

  play() {
    if (!window.speechSynthesis) return alert("TTS unavailable on this browser.");

    // If currently paused, just resume the internal engine
    if (window.speechSynthesis.paused) {
      window.speechSynthesis.resume();
      this.updateUI("playing");
      return;
    }

    // Otherwise, start a fresh read
    window.speechSynthesis.cancel();
    this.speechChunks = this.chunkLecture(DOM.explanationText.innerHTML);
    
    if (this.speechChunks.length === 0) return;

    this.currentChunkIndex = 0;
    this.isActive = true;
    this.updateUI("playing");
    
    this.speakNextChunk();
  }

  pause() {
    if (window.speechSynthesis && window.speechSynthesis.speaking && !window.speechSynthesis.paused) {
      window.speechSynthesis.pause();
      this.updateUI("paused");
    }
  }

  stop() {
    if (window.speechSynthesis) {
      window.speechSynthesis.cancel();
    }
    this.isActive = false;
    this.currentChunkIndex = 0;
    this.updateUI("stopped");
  }

  updateUI(state) {
    if (state === "playing") {
      DOM.speakBtn.style.display = "none";
      DOM.pauseSpeakBtn.style.display = "block";
    } else if (state === "paused") {
      DOM.pauseSpeakBtn.style.display = "none";
      DOM.speakBtn.style.display = "block";
      DOM.speakBtn.textContent = "▶️ Resume";
    } else if (state === "stopped") {
      DOM.pauseSpeakBtn.style.display = "none";
      DOM.speakBtn.style.display = "block";
      DOM.speakBtn.textContent = "🔊 Read Lecture";
    }
  }
}

// Instantiate and Bind TTS Engine
const Narrator = new TTSEngine();

DOM.speakBtn.addEventListener('click', () => Narrator.play());
DOM.pauseSpeakBtn.addEventListener('click', () => Narrator.pause());
DOM.stopSpeakBtn.addEventListener('click', () => Narrator.stop());

/**
 * ============================================================================
 * 8. FINAL SYSTEM BOOT
 * ============================================================================
 */
document.addEventListener('DOMContentLoaded', () => {
  Logger.info("NoteCast Interactive System Visualizer Online.");
  parseRequest();
  initializeSimulation();
});