import { authedFetch, requireAuth, logout, API_BASE } from "./api.js";

const videoId = new URLSearchParams(location.search).get("id");
if (!videoId) window.location.href = "dashboard.html";

let pollTimer = null;
let currentVideoTitle = "Study Notes";

// =========================================================================
// SMART WHITEBOARD CAPTURE ALGORITHM (Luminance, Memory Opt, Anti-Spam)
// =========================================================================
export class SmartWhiteboardCapture {
    constructor(videoElement, captureCallback) {
        this.video = videoElement;
        this.callback = captureCallback; 
        
        this.canvas = document.createElement('canvas');
        this.ctx = this.canvas.getContext('2d', { willReadFrequently: true });
        
        this.lastCapturedData = null;  
        this.previousFrameData = null; 
        
        this.frameBuffer = [];
        this.BUFFER_SIZE = 5; 
        
        this.STABLE_FRAMES_NEEDED = 2; 
        this.stableCount = 0;
        
        // Tuned for real-world lighting, shadows, and auto-exposure
        this.INSTANT_MOTION_THRESHOLD = 0.5;   
        this.SIGNIFICANT_CONTENT_CHANGE = 2.0; 
        this.WIPE_THRESHOLD = 15.0;            
        
        // Prevent spamming the backend (10 seconds between standard captures)
        this.CAPTURE_COOLDOWN = 10000; 
        this.lastCaptureTime = 0;

        this.interval = null;
    }

    start() {
        if (this.interval) clearInterval(this.interval);
        this.interval = setInterval(() => this.analyzeFrame(), 1000);
    }

    stop() {
        if (this.interval) clearInterval(this.interval);
    }

    analyzeFrame() {
        if (this.video.paused || this.video.ended) return;

        // Ensure canvas matches video resolution dynamically
        if (this.canvas.width !== this.video.videoWidth || this.canvas.height !== this.video.videoHeight) {
            this.canvas.width = this.video.videoWidth;
            this.canvas.height = this.video.videoHeight;
        }

        this.ctx.drawImage(this.video, 0, 0, this.canvas.width, this.canvas.height);
        
        // Extract raw image data (Fast, no JPEG compression overhead)
        const currentFrame = this.ctx.getImageData(0, 0, this.canvas.width, this.canvas.height);

        // Maintain the rolling buffer with raw ImageData to save CPU/Memory
        this.frameBuffer.push(currentFrame);
        if (this.frameBuffer.length > this.BUFFER_SIZE) {
            this.frameBuffer.shift();
        }

        if (!this.previousFrameData) {
            this.previousFrameData = currentFrame;
            this.lastCapturedData = currentFrame; 
            return;
        }

        const motionDiff = this.calculateDifference(this.previousFrameData, currentFrame);
        const now = Date.now();

        // 1. WIPE OR CAMERA CUT DETECTION
        if (motionDiff > this.WIPE_THRESHOLD) {
            let preWipeFrameData = null;
            if (this.frameBuffer.length >= 4) {
                preWipeFrameData = this.frameBuffer[this.frameBuffer.length - 4];
            } else if (this.frameBuffer.length > 0) {
                preWipeFrameData = this.frameBuffer[0];
            }

            if (preWipeFrameData) {
                const contentDiff = this.calculateDifference(this.lastCapturedData, preWipeFrameData);
                if (contentDiff > this.SIGNIFICANT_CONTENT_CHANGE) {
                    this.dispatchCapture(preWipeFrameData, "WIPE_EVENT: Board Erased / Transitioned");
                    this.lastCapturedData = currentFrame; 
                    this.lastCaptureTime = now;
                }
            }
            this.stableCount = 0;
        } 
        // 2. PROFESSOR WRITING / POINTING (Motion Occurring)
        else if (motionDiff > this.INSTANT_MOTION_THRESHOLD) {
            this.stableCount = 0; 
        } 
        // 3. SCENE IS STILL (Professor stepped away)
        else {
            this.stableCount++;
            
            if (this.stableCount >= this.STABLE_FRAMES_NEEDED) {
                const contentDiff = this.calculateDifference(this.lastCapturedData, currentFrame);
                
                // Only capture if enough content changed AND cooldown has expired
                if (contentDiff > this.SIGNIFICANT_CONTENT_CHANGE && (now - this.lastCaptureTime > this.CAPTURE_COOLDOWN)) {
                    this.dispatchCapture(currentFrame, "Unobstructed Whiteboard Capture");
                    this.lastCapturedData = currentFrame; 
                    this.lastCaptureTime = now;
                }
            }
        }
        
        this.previousFrameData = currentFrame;
    }

    // Helper: Only compress to DataURL when we actually decide to send to the backend
    dispatchCapture(imageData, reason) {
        this.ctx.putImageData(imageData, 0, 0);
        const dataURL = this.canvas.toDataURL('image/jpeg', 0.8);
        this.callback(dataURL, reason);
    }

    calculateDifference(frame1, frame2) {
        let diffPixels = 0;
        let totalChecked = 0;
        const data1 = frame1.data;
        const data2 = frame2.data;
        const len = data1.length;

        // Check every 4th pixel (step by 16 bytes: RGBA) for high-speed accuracy
        for (let i = 0; i < len; i += 16) {
            // Convert to grayscale/luminance to ignore minor color shifts & soft shadows
            // Formula: 0.299*R + 0.587*G + 0.114*B
            const lum1 = 0.299 * data1[i] + 0.587 * data1[i+1] + 0.114 * data1[i+2];
            const lum2 = 0.299 * data2[i] + 0.587 * data2[i+1] + 0.114 * data2[i+2];
            
            // Threshold of 25 (out of 255) ignores auto-exposure and soft shadows
            // Triggers strictly on stark contrast changes (marker/chalk on board)
            if (Math.abs(lum1 - lum2) > 25) { 
                diffPixels++;
            }
            totalChecked++;
        }
        return (diffPixels / totalChecked) * 100;
    }
}
// =========================================================================

function initAll() {
  setupTheme();
  bindUIEvents();
  startApp(); 
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", initAll);
} else {
  initAll(); 
}

function setupTheme() {
  const toggleBtn = document.getElementById("themeToggle");
  const currentTheme = localStorage.getItem("notecast_theme") || "light";
  document.documentElement.setAttribute("data-theme", currentTheme);

  if (toggleBtn) {
    toggleBtn.addEventListener("click", () => {
      const theme = document.documentElement.getAttribute("data-theme") === "light" ? "dark" : "light";
      document.documentElement.setAttribute("data-theme", theme);
      localStorage.setItem("notecast_theme", theme);
    });
  }
}

function renderMath(element) {
  if (window.renderMathInElement && element) {
    try {
      window.renderMathInElement(element, {
        delimiters: [
          {left: "$$", right: "$$", display: true},
          {left: "\\[", right: "\\]", display: true},
          {left: "$", right: "$", display: false},
          {left: "\\(", right: "\\)", display: false}
        ],
        throwOnError: false
      });
    } catch (e) {
      console.warn("KaTeX rendering warning:", e);
    }
  }
}

function bindUIEvents() {
  document.querySelectorAll(".tab").forEach((tab) => {
    tab.addEventListener("click", () => {
      document.querySelectorAll(".tab").forEach((t) => t.classList.remove("active"));
      tab.classList.add("active");
      document.querySelectorAll(".panel").forEach((p) => p.classList.add("hidden"));
      const targetPanel = document.getElementById(`panel-${tab.dataset.tab}`);
      if (targetPanel) targetPanel.classList.remove("hidden");
    });
  });

  const generateAiBtn = document.getElementById("generateAiBtn") || document.getElementById("generateAiNotesBtn");
  if (generateAiBtn) {
    generateAiBtn.addEventListener("click", async () => {
      document.querySelectorAll(".tab").forEach(t => t.classList.remove("active"));
      document.querySelectorAll(".panel").forEach(p => p.classList.add("hidden"));
      const aiTab = document.querySelector('[data-tab="ai-notes"]');
      if (aiTab) aiTab.classList.add("active");
      
      const aiPanel = document.getElementById("panel-ai-notes");
      if (aiPanel) aiPanel.classList.remove("hidden");
      
      const container = document.getElementById("aiNotesContainer") || document.getElementById("aiNotesContent");
      if (container) container.innerHTML = "<div class='empty-state'><em>Triggering deep AI research. This may take a minute...</em></div>";

      try {
        const res = await authedFetch(`/videos/${videoId}/generate-ai-notes`, { method: "POST" });
        if (res) {
          renderAiNotes(res);
          pollTimer = setTimeout(load, 2000); 
        } else {
          throw new Error("API Failed");
        }
      } catch (err) {
        console.error("AI Generation error:", err);
        if (container) container.innerHTML = `<div class="empty-state" style="color: var(--danger);">Failed to trigger AI generation. Check your connection.</div>`;
      }
    });
  }

  const deleteBtn = document.getElementById("deleteBtn") || document.getElementById("deleteVideoBtn");
  if (deleteBtn) {
    deleteBtn.addEventListener("click", async () => {
      if (confirm("Are you sure you want to delete this session?")) {
        try {
          const res = await authedFetch(`/videos/${videoId}`, { method: "DELETE" });
          if (res) window.location.href = "dashboard.html";
        } catch(e) {
          alert("Failed to delete session.");
        }
      }
    });
  }

  const signOutBtn = document.getElementById("signOutBtn") || document.getElementById("logoutBtn");
  if (signOutBtn) {
    signOutBtn.addEventListener("click", async (e) => {
      e.preventDefault();
      await logout();
      window.location.href = "login.html";
    });
  }

  document.querySelectorAll(".dl-pdf, .btn-pdf, #downloadPdfNotesBtn, #downloadPdfAiBtn, #downloadPdfTranscriptBtn, #downloadPdfBtn, #downloadPdfAiNotesBtn").forEach(btn => {
    if (btn) {
      btn.addEventListener("click", (e) => {
        e.preventDefault();
        secureDownload(`/videos/${videoId}/ai-notes/download-pdf`, `${sanitizeFilename(currentVideoTitle)}_Study_Guide.pdf`, 'application/pdf');
      });
    }
  });
  
  document.querySelectorAll(".dl-ppt, .btn-ppt, #downloadPptNotesBtn, #downloadPptAiBtn, #downloadPptAiNotesBtn").forEach(btn => {
    if (btn) {
      btn.addEventListener("click", (e) => {
        e.preventDefault();
        secureDownload(`/videos/${videoId}/ai-notes/download-ppt`, `${sanitizeFilename(currentVideoTitle)}_Master_Deck.pptx`, 'application/vnd.openxmlformats-officedocument.presentationml.presentation');
      });
    }
  });

  const downloadPdfCapturesBtn = document.getElementById("downloadPdfCapturesBtn");
  if (downloadPdfCapturesBtn) {
    downloadPdfCapturesBtn.addEventListener("click", (e) => {
      e.preventDefault();
      secureDownload(`/videos/${videoId}/download-pdf`, `${sanitizeFilename(currentVideoTitle)}_Captures.pdf`, 'application/pdf');
    });
  }

  const downloadPptCapturesBtn = document.getElementById("downloadPptCapturesBtn");
  if (downloadPptCapturesBtn) {
    downloadPptCapturesBtn.addEventListener("click", (e) => {
      e.preventDefault();
      secureDownload(`/videos/${videoId}/download-ppt`, `${sanitizeFilename(currentVideoTitle)}_Captures.pptx`, 'application/vnd.openxmlformats-officedocument.presentationml.presentation');
    });
  }
}

async function startApp() {
  try {
    const user = await requireAuth();
    const userNameEl = document.getElementById("userName");
    if (userNameEl) userNameEl.textContent = user.display_name || user.email;
    
    await load();
  } catch (err) {
    console.error("Auth or connection error:", err);
    const titleEl = document.getElementById("videoTitle");
    if (titleEl) titleEl.textContent = "Connection Error";
  }
}

async function load() {
  try {
    const video = await authedFetch(`/videos/${videoId}`);
    if (!video) return;

    currentVideoTitle = video.title || "Study_Notes";
    
    const titleEl = document.getElementById("videoTitle");
    if (titleEl) titleEl.textContent = video.title;
    
    const metaEl = document.getElementById("videoMeta");
    if (metaEl) metaEl.textContent = `${video.channel || "Unknown Channel"} · ${statusLabel(video.status)}`;

    const [notes, aiNotesData, transcript, visuals] = await Promise.all([
      authedFetch(`/videos/${videoId}/notes`),
      authedFetch(`/videos/${videoId}/ai-notes`),
      authedFetch(`/videos/${videoId}/transcript`),
      authedFetch(`/videos/${videoId}/visuals`),
    ]);

    renderNotes(notes);
    renderAiNotes(aiNotesData);
    renderTranscript(transcript);
    renderVisuals(visuals);

    clearTimeout(pollTimer);
    if (["initializing", "capturing", "processing"].includes(video.status)) {
      pollTimer = setTimeout(load, 4000);
    }
  } catch (err) {
    console.error("Error loading video data:", err);
  }
}

async function secureDownload(endpoint, filename, mimeType) {
  try {
    const response = await fetch(`${API_BASE}${endpoint}`, {
      method: 'GET',
      credentials: 'include',
    });

    if (!response.ok) {
        const errText = await response.text();
        throw new Error(`Server returned ${response.status}: ${errText}`);
    }

    const rawBlob = await response.blob();
    const blob = new Blob([rawBlob], { type: mimeType });

    const downloadUrl = window.URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.style.display = "none";
    a.href = downloadUrl;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    window.URL.revokeObjectURL(downloadUrl);
    a.remove();
  } catch (error) {
    console.error("Download failed:", error);
    alert(`Download failed: ${error.message}`);
  }
}

function sanitizeFilename(name) {
  return name.replace(/[^a-z0-9]/gi, '_').toLowerCase() || "download";
}

function statusLabel(status) {
  return { 
    initializing: "starting", 
    capturing: "capturing live", 
    processing: "processing", 
    completed: "ready", 
    failed: "processing failed" 
  }[status] || status;
}

function renderNotes(notes) {
  const container = document.getElementById("notesContainer");
  if (!container) return;

  const topLevel = (notes || []).filter((n) => !n.parent_id).sort((a, b) => a.order_index - b.order_index);
  
  if (!topLevel.length) {
    container.innerHTML = `<div class="empty-state">Notes will show up here once capture starts, and get reorganized once the video finishes.</div>`;
    return;
  }

  container.innerHTML = topLevel
    .map((section) => {
      return `
      <div class="note-section" style="margin-bottom: 24px; padding: 20px; background: var(--surface); border: 1px solid var(--border); border-radius: 8px;">
        <div class="note-heading" style="font-size: 1.3em; font-weight: 700; color: var(--text-main); border-bottom: 1px solid var(--border); padding-bottom: 8px; margin-bottom: 12px;">
          ${escapeHtml(section.heading)}
        </div>
        <div class="note-body markdown-body" style="color: var(--text-main); line-height: 1.6;">${mdToHtml(section.body_md)}</div>
        ${renderAssets(section.assets)}
      </div>`;
    })
    .join("");
    
  renderMath(container);
}

function renderAiNotes(data) {
  const container = document.getElementById("aiNotesContainer") || document.getElementById("aiNotesContent");
  if (!container) return;

  let markdownContent = "";
  if (typeof data === "string") {
    markdownContent = data;
  } else if (Array.isArray(data)) {
    markdownContent = data.map(item => item.body_md || item.ai_markdown || item.content || JSON.stringify(item)).join("\n\n");
  } else if (data && typeof data === "object") {
    markdownContent = data.ai_markdown || data.markdown || data.content || data.text || data.notes || data.body_md || "";
  }

  if (!markdownContent && data && data.data) {
    markdownContent = data.data.ai_markdown || data.data.markdown || data.data.content || data.data.text || "";
  }

  if (!markdownContent || markdownContent.trim() === "" || markdownContent.includes("Click **Generate AI Extensive Notes")) {
    container.innerHTML = `<div class="empty-state" style="padding: 20px; text-align: center; color: var(--text-muted);">
      Click <strong>Generate AI Extensive Notes</strong> above to synthesize a master study guide with code snippets & diagram references.
    </div>`;
    return;
  }
  container.innerHTML = `<div class="markdown-body" style="background: var(--surface); padding: 32px; border: 1px solid var(--border); border-radius: 12px; box-shadow: 0 4px 6px rgba(0,0,0,0.02); line-height: 1.7; color: var(--text-main);">
    ${mdToHtml(markdownContent)}
  </div>`;

  renderMath(container);
}

function renderAssets(assets) {
  if (!assets || !assets.length) return "";
  return assets
    .map((a) => {
      if (a.asset_type === "image" && a.storage_key) {
        return `<img src="${API_BASE}${a.storage_key}" style="max-width:100%; border:1px solid var(--border); border-radius:6px; margin:12px 0;" />`;
      }
      if (a.asset_type === "code") {
        return `<pre style="background: var(--code-bg); color: var(--text-main); padding:16px; border-radius:8px; overflow-x:auto; margin:12px 0;"><code>${escapeHtml(a.content || "")}</code></pre>`;
      }
      return "";
    })
    .join("");
}

function renderTranscript(segments) {
  const container = document.getElementById("transcriptContainer") || document.getElementById("transcriptContent");
  if (!container) return;

  if (!segments || !segments.length) {
    container.innerHTML = `<div class="empty-state">No transcript captured yet.</div>`;
    return;
  }
  container.innerHTML = segments
    .map((s) => `<div class="transcript-line" style="margin-bottom: 12px; line-height: 1.5;">
      <span class="transcript-ts" style="color: var(--primary); font-weight: 600; margin-right: 12px;">[${msToClock(s.start_ms)}]</span>
      <span style="color: var(--text-main);">${escapeHtml(s.text)}</span>
    </div>`)
    .join("");
}

function renderVisuals(visuals) {
  const container = document.getElementById("capturesContainer") || document.getElementById("visualsContent");
  if (!container) return;

  if (!visuals || !visuals.length) {
    container.innerHTML = `<div class="empty-state">No diagrams or slides captured yet.</div>`;
    return;
  }
  container.innerHTML = visuals
    .map((v) => `
      <div class="visual-card" style="margin-bottom: 20px; padding: 16px; background: var(--surface); border: 1px solid var(--border); border-radius: 8px;">
        ${v.storage_key ? `<img src="${API_BASE}${v.storage_key}" style="max-width: 100%; border-radius: 6px; margin-bottom: 12px;" />` : ""}
        <div class="visual-type" style="font-weight: 700; color: var(--primary); text-transform: uppercase; font-size: 0.85em; letter-spacing: 0.05em;">${escapeHtml(v.type)}</div>
        <div class="visual-desc" style="font-size: 0.95em; color: var(--text-muted); margin-top: 6px; line-height: 1.5;">${escapeHtml(v.description)}</div>
      </div>`
    )
    .join("");
}

function msToClock(ms) {
  const s = Math.floor(ms / 1000);
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const ss = String(s % 60).padStart(2, "0");
  return h ? `${h}:${String(m).padStart(2, "0")}:${ss}` : `${m}:${ss}`;
}

function escapeHtml(str) {
  return (str || "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

// =========================================================================
// O(N) LINE-BY-LINE "SMART ENGINE" (Safely handles lists, diagrams, tables)
// =========================================================================
function mdToHtml(md) {
  if (!md) return "";
  
  const lines = md.split('\n');
  const validTableLines = new Set();

  for (let i = 0; i < lines.length; i++) {
      let l = lines[i].trim();
      if (l.match(/^\|[\s\-:\|]+\|$/) && l.includes('---')) {
          validTableLines.add(i);
          let j = i - 1;
          while (j >= 0 && lines[j].trim().startsWith('|') && lines[j].trim().endsWith('|')) {
              validTableLines.add(j);
              j--;
          }
          j = i + 1;
          while (j < lines.length && lines[j].trim().startsWith('|') && lines[j].trim().endsWith('|')) {
              validTableLines.add(j);
              j++;
          }
      }
  }

  let inTable = false;
  let tableHtml = "";
  
  let inDiagram = false;
  let diagramHtml = [];
  
  let inList = false;
  let listType = "ul";
  let listHtml = [];
  
  let pBuffer = [];
  let htmlLines = [];

  function flushP() {
      if (pBuffer.length > 0) {
          htmlLines.push(`<p style="margin-bottom:18px; color: #334155;">${pBuffer.join('<br>')}</p>`);
          pBuffer = [];
      }
  }

  function flushDiagram() {
      if (diagramHtml.length > 0) {
          while (diagramHtml.length && diagramHtml[diagramHtml.length-1].trim() === '') diagramHtml.pop();
          if (diagramHtml.length > 0) {
              const content = escapeHtml(diagramHtml.join('\n'));
              htmlLines.push(`<div class="ascii-shape" style="background: var(--surface); border: 2px dashed #93c5fd; padding: 24px; border-radius: 12px; margin: 24px 0; overflow-x: auto; text-align: center; box-shadow: 0 4px 12px rgba(0,0,0,0.05);"><div style="display: inline-block; text-align: left;"><pre style="font-family: 'Courier New', Courier, monospace; font-weight: 700; color: #2563eb; background: transparent; border: none; padding: 0; margin: 0; line-height: 1.3;">${content}</pre></div></div>`);
          }
          diagramHtml = [];
          inDiagram = false;
      }
  }

  function flushTable() {
      if (inTable) {
          htmlLines.push(tableHtml + `</table></div>`);
          tableHtml = "";
          inTable = false;
      }
  }

  function flushList() {
      if (listHtml.length > 0) {
          htmlLines.push(`<${listType} style="margin-bottom:20px; padding-left:24px; color: #334155;">\n` + listHtml.join('\n') + `\n</${listType}>`);
          listHtml = [];
          inList = false;
      }
  }

  function flushAll() {
      flushP();
      flushList();
      flushDiagram();
      flushTable();
  }

  for (let i = 0; i < lines.length; i++) {
      let rawLine = lines[i];
      let line = rawLine.trim();

      if (!line) {
          flushP();
          flushList();
          if (inDiagram) {
              diagramHtml.push(rawLine); 
          } else {
              flushTable();
          }
          continue;
      }

      if (line.startsWith("```")) {
          flushAll();
          let codeContent = [];
          i++;
          while (i < lines.length && !lines[i].trim().startsWith("```")) {
              codeContent.push(escapeHtml(lines[i]));
              i++;
          }
          htmlLines.push(`<pre class="custom-code" style="background: var(--code-bg); color: var(--text-main); padding:16px; border:1px solid var(--border); border-radius:8px; overflow-x:auto; margin:16px 0; font-family: monospace;"><code>${codeContent.join('\n')}</code></pre>`);
          continue;
      }

      if (line.match(/^#{1,6}\s/)) {
          flushAll();
          let safeLine = escapeHtml(line);
          if (line.startsWith('### ')) {
              htmlLines.push(`<h3 style='margin-top:24px; margin-bottom:12px; color: #0f172a; font-size: 1.25em; border-bottom: 1px solid var(--border); padding-bottom: 6px;'>${safeLine.substring(4)}</h3>`);
          } else if (line.startsWith('## ')) {
              htmlLines.push(`<h2 style='margin-top:32px; margin-bottom:16px; color: #0f172a; border-bottom:2px solid #e2e8f0; padding-bottom:10px; font-size: 1.6em;'>${safeLine.substring(3)}</h2>`);
          } else if (line.startsWith('# ')) {
              htmlLines.push(`<h1 style='margin-top:32px; margin-bottom:16px; color: #0f172a; font-size: 2em;'>${safeLine.substring(2)}</h1>`);
          }
          continue;
      }

      if (validTableLines.has(i)) {
          flushP();
          flushList();
          flushDiagram();
          if (!inTable) {
              inTable = true;
              tableHtml = `<div class="custom-table" style="overflow-x:auto; margin-bottom: 24px; box-shadow: 0 2px 8px rgba(0,0,0,0.03); border-radius: 8px;"><table style="width: 100%; border-collapse: collapse; text-align: left; background: var(--surface); border: 1px solid var(--border); border-radius: 8px; overflow: hidden;">`;
          }
          
          if (line.match(/^\|[\s\-:\|]+\|$/) && line.includes('---')) continue; 
          
          let cells = line.split('|').slice(1, -1).map(c => escapeHtml(c.trim()));
          let isHeader = (tableHtml.indexOf("<th") === -1 && lines[i+1] && lines[i+1].trim().match(/^[\s\|-]+$/));
          let rowBg = isHeader ? "background: #f8fafc;" : (tableHtml.split("<tr>").length % 2 === 0 ? "background: #f1f5f9;" : "background: transparent;");
          let rowHtml = `<tr style="${rowBg}">`;
          
          cells.forEach(cell => {
              let tag = isHeader ? "th" : "td";
              let style = isHeader 
                  ? "padding: 14px; border-bottom: 2px solid #cbd5e1; font-weight: 700; color: #0f172a;" 
                  : "padding: 14px; border-bottom: 1px solid var(--border); color: #334155;";
              
              let formattedCell = cell
                  .replace(/\*\*(.+?)\*\*/g, "<strong style='color: #2563eb; font-weight: 700;'>$1</strong>")
                  .replace(/\*(.+?)\*/g, "<em style='color: #475569;'>$1</em>")
                  .replace(/`([^`\n]+)`/g, "<code style='background: #fee2e2; padding:3px 6px; border-radius:4px; color: #b91c1c; font-family: monospace; font-size: 0.9em;'>$1</code>");
              rowHtml += `<${tag} style="${style}">${formattedCell}</${tag}>`;
          });
          rowHtml += "</tr>";
          tableHtml += rowHtml;
          continue;
      }

      const isDiag = !validTableLines.has(i) && (
          rawLine.includes('+--') || 
          rawLine.includes('--+') || 
          rawLine.includes('-->') || 
          rawLine.includes('<--') || 
          rawLine.match(/\| {2,}/) || 
          rawLine.match(/\s{2,}\|/) ||
          (line.startsWith('|') && line.endsWith('|'))
      );

      if (inDiagram) {
          if (isDiag || line === '') {
              diagramHtml.push(rawLine);
              continue;
          } else {
              flushDiagram();
          }
      } else if (isDiag) {
          flushP();
          flushList();
          flushTable();
          inDiagram = true;
          diagramHtml.push(rawLine);
          continue;
      }

      const isBullet = line.startsWith("- ");
      const isNum = line.match(/^\d+\.\s/);
      if (isBullet || isNum) {
          flushP();
          flushDiagram();
          flushTable();

          let currentType = isBullet ? "ul" : "ol";
          if (!inList) {
              inList = true;
              listType = currentType;
          } else if (inList && listType !== currentType) {
              flushList();
              inList = true;
              listType = currentType;
          }

          let textContent = isBullet ? line.substring(2) : line.replace(/^\d+\.\s/, '');
          let formattedText = escapeHtml(textContent)
              .replace(/\*\*(.+?)\*\*/g, "<strong style='color: #2563eb; font-weight: 700;'>$1</strong>")
              .replace(/\*(.+?)\*/g, "<em style='color: #475569;'>$1</em>")
              .replace(/`([^`\n]+)`/g, "<code style='background: #fee2e2; padding:3px 6px; border-radius:4px; color: #b91c1c; font-family: monospace; font-size: 0.9em;'>$1</code>");

          listHtml.push(`<li style="margin-bottom:10px;">${formattedText}</li>`);
          continue;
      }

      flushList();
      flushDiagram();
      flushTable();
      
      let safeLine = escapeHtml(rawLine)
          .replace(/\*\*(.+?)\*\*/g, "<strong style='color: #2563eb; font-weight: 700;'>$1</strong>")
          .replace(/\*(.+?)\*/g, "<em style='color: #475569;'>$1</em>")
          .replace(/`([^`\n]+)`/g, "<code style='background: #fee2e2; padding:3px 6px; border-radius:4px; color: #b91c1c; font-family: monospace; font-size: 0.9em;'>$1</code>");
      
      if (safeLine.startsWith("&gt; ")) {
          safeLine = `<blockquote style="border-left: 4px solid #cbd5e1; padding-left: 16px; margin: 16px 0; color: #475569; font-style: italic;">${safeLine.substring(5)}</blockquote>`;
      }
      pBuffer.push(safeLine);
  }

  flushAll();
  return htmlLines.join('\n');
}