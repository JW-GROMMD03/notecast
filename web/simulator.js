// ============================================================================
// NOTECAST AI HTML VISUALIZER CONTROLLER (EXTENDED TIMEOUT, DUAL-MODE ENGINE)
// Features: Dual Mode (Static Library & Extended AI Generation), 120s Extended
// Connection Keep-Alive, Session Caching, Telemetry PostMessage Receiver, 
// and Enterprise Text-to-Speech (TTS) Chunking Engine.
// ============================================================================

"use strict";

/**
 * ============================================================================
 * 1. CONFIGURATION & STATE MANAGEMENT
 * ============================================================================
 */
const CONFIG = {
  CACHE_TTL_MS: 1000 * 60 * 60, // 1 Hour Cache validity
  MAX_TIMEOUT_MS: 120000,       // Extended 120-second socket window
  STATIC_SIM_BASE_PATH: "/static/simulations/",
  TTS_RATE: 0.95,
  TTS_PITCH: 1.0,
  DEFAULT_TOPIC: "Interactive System Architecture"
};

const STATE = {
  isGenerating: false,
  isSpeaking: false,
  currentSchema: null,
  activeMetrics: new Set(),
  requestedTopic: "",
  requestedFile: "",
  isStaticMode: false,
  loadingIntervalId: null
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
  refreshSimBtn: document.getElementById('refreshSimBtn'),
  modeMetricVal: document.getElementById('modeMetricVal')
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
    const rawFile = urlParams.get('file');

    if (rawFile) {
      STATE.isStaticMode = true;
      STATE.requestedFile = decodeURIComponent(rawFile.trim());
      STATE.requestedTopic = urlParams.get('title') ? decodeURIComponent(urlParams.get('title')) : STATE.requestedFile.split('/').pop().replace('.html', '');
      Logger.info(`Static File Mode activated: "${STATE.requestedFile}"`);
    } else {
      STATE.isStaticMode = false;
      STATE.requestedTopic = rawTopic ? decodeURIComponent(rawTopic.trim()) : CONFIG.DEFAULT_TOPIC;
      Logger.info(`AI Dynamic Mode activated: "${STATE.requestedTopic}"`);
    }
  } catch (error) {
    Logger.error("Failed to parse URL parameters. Defaulting to fallback topic.", error);
    STATE.requestedTopic = CONFIG.DEFAULT_TOPIC;
    STATE.isStaticMode = false;
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
 * 5. EXTENDED CONNECTION FETCH ENGINE (120s TIMEOUT NO ABORT PREMATURELY)
 * ============================================================================
 */
async function fetchWithExtendedTimeout(url, options, timeoutMs = CONFIG.MAX_TIMEOUT_MS) {
  const controller = new AbortController();
  const timeoutId = setTimeout(() => {
    Logger.warn(`Extended connection threshold (${timeoutMs / 1000}s) reached. Aborting.`);
    controller.abort();
  }, timeoutMs);

  try {
    const res = await fetch(url, {
      ...options,
      signal: controller.signal,
      credentials: "include" // Preserves cross-origin session authentication
    });
    clearTimeout(timeoutId);

    if (!res.ok) {
      throw new Error(`Server returned HTTP ${res.status}: ${res.statusText}`);
    }
    return await res.json();
  } catch (err) {
    clearTimeout(timeoutId);
    if (err.name === 'AbortError') {
      throw new Error("Generation timeout: The AI provider took longer than 120 seconds to respond.");
    }
    throw err;
  }
}

/**
 * Animated Loading State with cycling progress indicators so users know
 * the connection is active during long multi-provider fallback cycles.
 */
function injectLoadingState() {
  DOM.iframe.classList.add('loading');
  DOM.headerTitle.textContent = `Synthesizing: ${STATE.requestedTopic}...`;
  
  const statusMessages = [
    "Contacting AI Model Cluster...",
    "Synthesizing Interactive HTML canvas layout...",
    "Writing real-time JavaScript physics and state machine...",
    "Formatting degree-level academic analysis...",
    "Finalizing visual DOM tree..."
  ];
  let msgIdx = 0;

  DOM.explanationText.innerHTML = `
    <div style="color: #60a5fa; font-weight: bold; margin-bottom: 12px; font-size: 1.1rem; border-bottom: 1px solid #1e293b; padding-bottom: 8px;">
      Establishing Secure LLM Pipeline...
    </div>
    <p style="color: #cbd5e1; line-height: 1.6;" id="loadingStatusText">
      Please wait while the generative engine synthesizes a complete interactive simulation tailored explicitly for <strong>${STATE.requestedTopic}</strong>.
    </p>
    <div style="background: rgba(59, 130, 246, 0.1); border: 1px stroke rgba(59, 130, 246, 0.3); border-radius: 8px; padding: 12px; margin-top: 15px; font-size: 0.85rem; color: #93c5fd;">
      ⏳ <em>Extended connection active. Models can take up to 30s for deep logic.</em>
    </div>
  `;

  if (STATE.loadingIntervalId) clearInterval(STATE.loadingIntervalId);
  STATE.loadingIntervalId = setInterval(() => {
    msgIdx = (msgIdx + 1) % statusMessages.length;
    const el = document.getElementById('loadingStatusText');
    if (el) {
      el.innerHTML = `Current Stage: <strong>${statusMessages[msgIdx]}</strong><br><span style="font-size:0.8rem; color:#64748b;">Generating ${STATE.requestedTopic} environment...</span>`;
    }
  }, 4500);

  DOM.iframe.srcdoc = `
    <!DOCTYPE html>
    <html>
    <body style="margin:0; background:#02040a; color:#3b82f6; display:flex; flex-direction:column; align-items:center; justify-content:center; height:100vh; font-family:-apple-system, BlinkMacSystemFont, sans-serif;">
      <div style="width:64px; height:64px; border:4px solid #0f172a; border-top:4px solid #3b82f6; border-right:4px solid #3b82f6; border-radius:50%; animation:spin 1s cubic-bezier(0.55, 0.085, 0.68, 0.53) infinite; box-shadow: 0 0 15px rgba(59, 130, 246, 0.2);"></div>
      <h3 style="margin-top:25px; color:#f8fafc; font-weight:700; letter-spacing:0.5px; font-size: 1.2rem;">Booting Execution Engine</h3>
      <p style="color:#64748b; font-size:0.95rem; text-align:center; max-width:400px; margin-top:10px; line-height: 1.5;">Synthesizing geometric topology, state controls, and event listeners...</p>
      <style>@keyframes spin { 0% { transform: rotate(0deg); } 100% { transform: rotate(360deg); } }</style>
    </body>
    </html>
  `;
}

async function initializeSimulation(forceRefresh = false) {
  if (STATE.isGenerating) return;
  STATE.isGenerating = true;

  // Handle Static Syllabus File Mode
  if (STATE.isStaticMode) {
    if (DOM.modeMetricVal) DOM.modeMetricVal.textContent = "Pre-compiled Static";
    DOM.headerTitle.textContent = STATE.requestedTopic;
    DOM.simHeading.textContent = "Module Details";
    DOM.simDesc.textContent = `Pre-compiled syllabus simulation for ${STATE.requestedTopic}`;
    DOM.explanationText.innerHTML = "<em>Loading pre-built module lecture data from static assets...</em>";

    const fullPath = CONFIG.STATIC_SIM_BASE_PATH + STATE.requestedFile;
    DOM.iframe.onload = () => {
      Logger.info("Static file rendered successfully.");
      DOM.iframe.classList.remove('loading');
      STATE.isGenerating = false;
    };
    DOM.iframe.src = fullPath;
    return;
  }

  // Handle AI Dynamic Generation Mode
  if (DOM.modeMetricVal) DOM.modeMetricVal.textContent = "Live AI Dynamic";
  if (forceRefresh) CacheManager.invalidate();

  let schema = CacheManager.get();

  if (!schema) {
    // Check if passed via sessionStorage from dashboard search
    const sessionActive = sessionStorage.getItem("active_sim_schema");
    if (sessionActive && !forceRefresh) {
      try {
        schema = JSON.parse(sessionActive);
        sessionStorage.removeItem("active_sim_schema");
      } catch (e) {
        schema = null;
      }
    }
  }

  if (!schema) {
    injectLoadingState();

    try {
      schema = await fetchWithExtendedTimeout("/diagrams/generate-sim/", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ topic: STATE.requestedTopic })
      }, CONFIG.MAX_TIMEOUT_MS);

      if (STATE.loadingIntervalId) clearInterval(STATE.loadingIntervalId);

      if (schema && schema.html_code) {
        CacheManager.set(schema);
      } else {
        throw new Error("Invalid schema structure returned from API endpoint.");
      }
    } catch (err) {
      if (STATE.loadingIntervalId) clearInterval(STATE.loadingIntervalId);
      Logger.error("Simulation Generation Halts:", err);
      DOM.explanationText.innerHTML = `
        <div style="background: rgba(239, 68, 68, 0.1); border: 1px solid #ef4444; padding: 15px; border-radius: 8px;">
          <h4 style="margin: 0 0 10px 0; color: #ef4444;">Generation Notice</h4>
          <p style="margin: 0; color: #f8fafc; font-size: 0.9rem;">${err.message || 'The backend API failed to respond. Please check provider keys.'}</p>
        </div>
      `;
      DOM.iframe.classList.remove('loading');
      STATE.isGenerating = false;
      return;
    }
  }

  STATE.currentSchema = schema;

  // Hydrate UI Shell
  DOM.headerTitle.textContent = schema.title || STATE.requestedTopic;
  DOM.simHeading.textContent = "Architecture Details";
  DOM.simDesc.textContent = schema.description || `Live interactive model for ${STATE.requestedTopic}`;
  DOM.explanationText.innerHTML = schema.detailed_lecture || "<em>No detailed lecture generated for this context.</em>";

  // Safely inject code into iframe
  DOM.iframe.onload = () => {
    Logger.info("Iframe execution initialized successfully.");
    DOM.iframe.classList.remove('loading');
    STATE.isGenerating = false;
  };

  DOM.iframe.srcdoc = schema.html_code;
}

// Bind Refresh Button
if (DOM.refreshSimBtn) {
  DOM.refreshSimBtn.addEventListener('click', () => {
    if (confirm("This will trigger a new AI generation and overwrite the current visualizer layout. Continue?")) {
      initializeSimulation(true);
    }
  });
}

/**
 * ============================================================================
 * 6. SECURE CROSS-FRAME TELEMETRY (IFRAME -> PARENT POSTMESSAGE)
 * ============================================================================
 */
window.addEventListener("message", (event) => {
  if (!event.data || typeof event.data !== 'object') return;

  // Handle static module metadata injection
  if (event.data.type === 'SIM_META') {
    if (event.data.lecture) DOM.explanationText.innerHTML = event.data.lecture;
    if (event.data.desc) DOM.simDesc.textContent = event.data.desc;
    return;
  }

  // Handle live metric updates
  if (event.data.type === 'UPDATE_METRIC') {
    const { title, value } = event.data;
    if (!title || value === undefined) return;

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
      const valEl = document.getElementById(`${safeId}_val`);
      if (valEl.textContent !== String(value)) {
        valEl.textContent = value;
        metricEl.style.transform = "scale(1.04)";
        metricEl.style.borderColor = "rgba(59, 130, 246, 0.8)";
        metricEl.style.background = "rgba(59, 130, 246, 0.15)";

        setTimeout(() => {
          metricEl.style.transform = "scale(1)";
          metricEl.style.borderColor = "rgba(59, 130, 246, 0.2)";
          metricEl.style.background = "rgba(59, 130, 246, 0.06)";
        }, 200);
      }
    }
  }
});

/**
 * ============================================================================
 * 7. ENTERPRISE TEXT-TO-SPEECH (TTS) CHUNKING ENGINE
 * Splits text into sentence boundaries to avoid 15-second browser audio drops.
 * ============================================================================
 */
class TTSEngine {
  constructor() {
    this.voices = [];
    this.speechChunks = [];
    this.currentChunkIndex = 0;
    this.isActive = false;

    if (window.speechSynthesis) {
      window.speechSynthesis.onvoiceschanged = this.populateVoices.bind(this);
      this.populateVoices();
    }
  }

  populateVoices() {
    this.voices = window.speechSynthesis.getVoices();
    DOM.voiceSelect.innerHTML = "";
    if (this.voices.length === 0) return;

    this.voices.forEach((v, index) => {
      const option = document.createElement('option');
      option.value = index;
      option.textContent = `${v.name} (${v.lang})`;

      if (v.default || v.lang === 'en-GB' || v.lang === 'en-US') {
        option.selected = true;
      }
      DOM.voiceSelect.appendChild(option);
    });
    Logger.info(`Loaded ${this.voices.length} TTS profiles.`);
  }

  chunkLecture(rawHTML) {
    const cleanText = rawHTML.replace(/<[^>]*>?/gm, ' ').replace(/\s+/g, ' ');
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

    if (window.speechSynthesis.paused) {
      window.speechSynthesis.resume();
      this.updateUI("playing");
      return;
    }

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

if (DOM.speakBtn) DOM.speakBtn.addEventListener('click', () => Narrator.play());
if (DOM.pauseSpeakBtn) DOM.pauseSpeakBtn.addEventListener('click', () => Narrator.pause());
if (DOM.stopSpeakBtn) DOM.stopSpeakBtn.addEventListener('click', () => Narrator.stop());

/**
 * ============================================================================
 * 8. SYSTEM BOOT
 * ============================================================================
 */
document.addEventListener('DOMContentLoaded', () => {
  Logger.info("NoteCast Interactive Visualizer Online.");
  parseRequest();
  initializeSimulation();
});