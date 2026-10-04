import { API_BASE, WS_BASE } from "./config.js";

let ws = null;
let currentSession = null; 
let audioBuffer = []; 

chrome.sidePanel.setPanelBehavior({ openPanelOnActionClick: true })
  .catch((error) => console.error("Side panel behavior error:", error));

chrome.tabs.onUpdated.addListener(async (tabId, changeInfo, tab) => {
  if (!tab.url) return;
  if (tab.url.includes("youtube.com/watch")) {
    await chrome.sidePanel.setOptions({ tabId, path: "sidepanel.html", enabled: true }).catch(() => {});
    
    if (currentSession && currentSession.tabId === tabId && changeInfo.status === "complete") {
      chrome.tabs.sendMessage(tabId, { scope: "notecast-content", type: "START_FRAMES" }).catch(() => {});
    }
  } else {
    await chrome.sidePanel.setOptions({ tabId, enabled: false }).catch(() => {});
  }
});

async function getSession() {
  const s = await chrome.storage.local.get(["accessToken", "refreshToken", "expiresAt", "userId", "email", "displayName"]);
  return s.accessToken ? s : null;
}

async function saveSession({ access_token, refresh_token, expires_in, user_id, email, display_name }) {
  await chrome.storage.local.set({
    accessToken: access_token,
    refreshToken: refresh_token,
    expiresAt: Date.now() + expires_in * 1000,
    userId: user_id,
    email,
    displayName: display_name,
  });
}

async function clearSession() {
  await chrome.storage.local.remove(["accessToken", "refreshToken", "expiresAt", "userId", "email", "displayName"]);
}

async function ensureFreshToken() {
  const session = await getSession();
  if (!session) throw new Error("Not logged in");
  if (session.expiresAt - Date.now() > 60_000) return session.accessToken;

  const resp = await fetch(`${API_BASE}/auth/refresh`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ refresh_token: session.refreshToken }),
  });
  if (!resp.ok) {
    await clearSession();
    throw new Error("Session expired — please sign in again");
  }
  const data = await resp.json();
  await saveSession(data);
  return data.access_token;
}

async function apiFetch(path, options = {}) {
  const token = await ensureFreshToken();
  const headers = { "Content-Type": "application/json", Authorization: `Bearer ${token}`, ...(options.headers || {}) };
  const resp = await fetch(`${API_BASE}${path}`, { ...options, headers });
  if (!resp.ok) {
    const body = await resp.json().catch(() => ({ detail: resp.statusText }));
    const err = new Error(body.detail || `Request failed (${resp.status})`);
    err.status = resp.status;
    throw err;
  }
  return resp.json();
}

function broadcast(message) {
  try {
    chrome.runtime.sendMessage(message).catch(() => {}); 
  } catch (e) {}
}

async function startCapturePipeline({ tabId, videoMeta }, sendResponse) {
  if (currentSession && currentSession.videoId) {
    sendResponse({ ok: true, session: currentSession });
    return;
  }

  try {
    audioBuffer = [];

    // Initialize the backend API session
    const token = await ensureFreshToken();
    const video = await apiFetch("/videos", { method: "POST", body: JSON.stringify(videoMeta) });
    await apiFetch(`/videos/${video.id}/consent`, { method: "POST", body: JSON.stringify({ scope: "audio,video,transcript" }) });
    const session = await apiFetch(`/videos/${video.id}/sessions?seed_transcript=`, { method: "POST" });

    currentSession = { sessionId: session.id, videoId: video.id, tabId };

    const wsUrl = `${WS_BASE}/ws/session/${session.id}?token=${encodeURIComponent(token)}`;
    console.log("NoteCast: Connecting to WebSocket ->", wsUrl);

    ws = new WebSocket(wsUrl);
    
    ws.onmessage = (event) => {
      try {
        const msg = JSON.parse(event.data);
        broadcast({ scope: "notecast", ...msg });
      } catch (e) {
        console.error("Failed to parse incoming WS message:", e);
      }
    };
    
    ws.onclose = (event) => {
      console.log("NoteCast: WebSocket closed:", event);
      broadcast({ scope: "notecast", type: "ws_closed" });
    };
    
    ws.onerror = (error) => {
      console.error("NoteCast: WebSocket error encountered:", error);
    };

    await new Promise((resolve, reject) => {
      const timer = setTimeout(() => reject(new Error("WebSocket connection timeout")), 5000);
      ws.addEventListener("open", () => {
        clearTimeout(timer);
        resolve();
      }, { once: true });
      ws.addEventListener("error", (err) => {
        clearTimeout(timer);
        reject(new Error("WebSocket connection failed: " + JSON.stringify(err)));
      }, { once: true });
    });

    // Flush any audio chunks sidepanel.js already captured while we connected
    while (audioBuffer.length > 0) {
      const bufferedPayload = audioBuffer.shift();
      if (ws && ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify(bufferedPayload));
      }
    }

    chrome.tabs.sendMessage(tabId, { scope: "notecast-content", type: "START_FRAMES" }).catch(() => {});

    broadcast({ scope: "notecast", type: "session_started", video, session });
    sendResponse({ ok: true, video, session });

  } catch (error) {
     console.error("Capture Pipeline Error:", error);
     sendResponse({ ok: false, error: error.message });
  }
}

async function stopCapture() {
  if (!currentSession) return;
  const { tabId, videoId } = currentSession;
  
  chrome.tabs.sendMessage(tabId, { scope: "notecast-content", type: "STOP_FRAMES" }).catch(() => {});

  if (ws && ws.readyState === WebSocket.OPEN) {
    ws.close();
  }
  ws = null;
  audioBuffer = [];

  try {
    const result = await apiFetch(`/videos/${videoId}/finalize`, { method: "POST" });
    broadcast({ scope: "notecast", type: "finalizing" });
    currentSession = null;
    return result;
  } catch (err) {
    console.error("Error finalizing session:", err);
    currentSession = null;
    throw err;
  }
}

function sendWs(payload) {
  if (ws && ws.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify(payload));
  } else {
    audioBuffer.push(payload);
  }
}

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (!message || message.scope !== "notecast") {
    return false;
  }

  if (message.type === "START_CAPTURE_PIPELINE") {
     startCapturePipeline(message.payload, sendResponse);
     return true; 
  }

  (async () => {
    try {
      switch (message.type) {
        case "LOGIN": {
          const resp = await fetch(`${API_BASE}/auth/login`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ email: message.email, password: message.password }),
          });
          const data = await resp.json().catch(() => ({}));
          if (!resp.ok) {
            sendResponse({ ok: false, status: resp.status, error: data.detail || "Sign in failed" });
            break;
          }
          await saveSession(data);
          sendResponse({ ok: true, displayName: data.display_name, email: data.email });
          break;
        }
        case "LOGOUT": {
          try { await apiFetch("/auth/logout", { method: "POST", body: JSON.stringify({}) }); } catch {}
          await clearSession();
          sendResponse({ ok: true });
          break;
        }
        case "GET_AUTH": {
          const session = await getSession();
          sendResponse(session ? { loggedIn: true, displayName: session.displayName, email: session.email } : { loggedIn: false });
          break;
        }
        case "STOP_CAPTURE": {
          const result = await stopCapture();
          sendResponse({ ok: true, ...result });
          break;
        }
        case "AUDIO_CHUNK":
          sendWs({ type: "audio_chunk", seq: message.seq, data_b64: message.data_b64, duration_ms: message.duration_ms, mime: "audio/webm" });
          sendResponse({ ok: true });
          break;
        case "FRAME":
          sendWs({ type: "frame", timestamp_ms: message.timestamp_ms, data_b64: message.data_b64 });
          sendResponse({ ok: true });
          break;
        default:
          sendResponse({ ok: false, error: `unknown message type: ${message.type}` });
      }
    } catch (err) {
      console.error("Background message handler error:", err);
      sendResponse({ ok: false, error: err.message });
    }
  })();

  return true; 
});