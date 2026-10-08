import { authedFetch, requireAuth, logout, apiFetch } from "./api.js";

let user;
let dueFlashcards = [];
let currentFcIndex = 0;
let networkGraph = null;
let editHistory = []; // Undo stack for Docu-Vision editor

// --- THEME ENGINE ---
const themeToggleBtn = document.getElementById("themeToggleBtn");
const themeIcon = document.getElementById("themeIcon");
const themeText = document.getElementById("themeText");

function applyTheme(theme) {
  document.documentElement.setAttribute("data-theme", theme);
  localStorage.setItem("theme", theme);
  
  if (theme === "light") {
    themeIcon.textContent = "🌙";
    themeText.textContent = "Dark Mode";
  } else {
    themeIcon.textContent = "☀️";
    themeText.textContent = "Light Mode";
  }
  
  // If the Knowledge Graph is currently visible, redraw it to update the colors
  if (networkGraph && document.getElementById("pane-graph").classList.contains("active")) {
    loadGraph();
  }
}

// Load saved theme or system preference
const savedTheme = localStorage.getItem("theme") || (window.matchMedia("(prefers-color-scheme: light)").matches ? "light" : "dark");
applyTheme(savedTheme);

if (themeToggleBtn) {
  themeToggleBtn.addEventListener("click", () => {
    const currentTheme = document.documentElement.getAttribute("data-theme");
    applyTheme(currentTheme === "light" ? "dark" : "light");
  });
}


async function init() {
  user = await requireAuth();
  document.getElementById("userName").textContent = user.display_name || user.email;
  document.getElementById("userPlanBadge").textContent = `Plan: ${user.plan || 'Free'}`;
  
  const tierDisplay = document.getElementById("currentTierDisplay");
  if (tierDisplay) {
    tierDisplay.textContent = user.plan || 'Free Plan';
  }

  // 1. Sidebar Tab Switching Engine
  document.querySelectorAll(".nav-item").forEach(item => {
    item.addEventListener("click", () => {
      document.querySelectorAll(".nav-item").forEach(n => n.classList.remove("active"));
      document.querySelectorAll(".tab-pane").forEach(p => p.classList.remove("active"));

      item.classList.add("active");
      const tabName = item.getAttribute("data-tab");
      document.getElementById(`pane-${tabName}`).classList.add("active");

      // Trigger lazy-loading for specific tabs
      if (tabName === "notes") loadVideos();
      if (tabName === "documents") loadDocuments();
      if (tabName === "flashcards") loadFlashcards();
      if (tabName === "graph") loadGraph();
    });
  });

  // 2. Wire Dynamic Simulation Generator
  const generateSimBtn = document.getElementById("generateSimBtn");
  if (generateSimBtn) {
    generateSimBtn.addEventListener("click", async () => {
      const topic = document.getElementById("simTopicInput").value.trim();
      if (!topic) return alert("Please enter a topic or unit name!");

      generateSimBtn.disabled = true;
      generateSimBtn.textContent = "AI Synthesizing...";
      try {
        const schema = await apiFetch("/diagrams/generate-sim", {
          method: "POST",
          body: JSON.stringify({ topic })
        });
        sessionStorage.setItem("active_sim_schema", JSON.stringify(schema));
        window.location.href = `simulator.html?topic=${encodeURIComponent(topic)}`;
      } catch (err) {
        alert("Failed to generate simulation. Please check your provider keys.");
      } finally {
        generateSimBtn.disabled = false;
        generateSimBtn.textContent = "Generate Live Simulation";
      }
    });
  }

  // 3. Docu-Vision Editor & Shape Insertion (Lucid-style)
  const summaryEditor = document.getElementById("docSummaryEditor");
  if (summaryEditor) {
    summaryEditor.addEventListener("input", () => {
      editHistory.push(summaryEditor.value);
      if (editHistory.length > 20) editHistory.shift();
    });

    const undoBtn = document.getElementById("undoBtn");
    if (undoBtn) {
      undoBtn.addEventListener("click", () => {
        if (editHistory.length > 1) {
          editHistory.pop();
          summaryEditor.value = editHistory[editHistory.length - 1];
        } else {
          summaryEditor.value = "";
        }
      });
    }

    document.querySelectorAll(".shape-btn[data-insert]").forEach(btn => {
      btn.addEventListener("click", () => {
        const shapeTag = btn.getAttribute("data-insert");
        const cursorPosition = summaryEditor.selectionStart;
        const textBefore = summaryEditor.value.substring(0, cursorPosition);
        const textAfter = summaryEditor.value.substring(cursorPosition);
        
        summaryEditor.value = `${textBefore}\n\n${shapeTag}\n\n${textAfter}`;
        editHistory.push(summaryEditor.value);
      });
    });
  }

  // 4. Wire PDF Upload (Docu-Vision)
  const uploadPdfBtn = document.getElementById("uploadPdfBtn");
  if (uploadPdfBtn) {
    uploadPdfBtn.addEventListener("click", async () => {
      const fileInput = document.getElementById("pdfUpload");
      if (!fileInput.files[0]) return alert("Please select a PDF first.");

      const btn = document.getElementById("uploadPdfBtn");
      btn.disabled = true;
      btn.textContent = "Uploading...";

      const formData = new FormData();
      formData.append("file", fileInput.files[0]);

      try {
        const res = await fetch("https://notecast-web.onrender.com/api/documents/upload", {
          method: "POST",
          credentials: "include", 
          body: formData
        });
        if (!res.ok) throw new Error("Upload failed");
        alert("Document uploaded! The AI is analyzing it in the background.");
        loadDocuments();
        fileInput.value = "";
      } catch (err) {
        alert("Error uploading document.");
      } finally {
        btn.disabled = false;
        btn.textContent = "Analyze Document";
      }
    });
  }

  // 5. Flashcard Answer Reveal & SM-2 Review Actions
  const fcShowBtn = document.getElementById("fcShowBtn");
  if (fcShowBtn) {
    fcShowBtn.addEventListener("click", () => {
      fcShowBtn.style.display = "none";
      document.getElementById("fcBack").style.display = "block";
      document.getElementById("fcControls").style.display = "flex";
    });
  }

  document.querySelectorAll(".btn-fc").forEach(btn => {
    btn.addEventListener("click", async (e) => {
      const quality = parseInt(e.target.getAttribute("data-q"));
      const cardId = dueFlashcards[currentFcIndex].id;
      try {
        await apiFetch(`/flashcards/review/${cardId}`, {
          method: "POST",
          body: JSON.stringify({ quality })
        });
      } catch (err) {
        console.error("Failed to submit flashcard review", err);
      }
      currentFcIndex++;
      renderCurrentFlashcard();
    });
  });

  // 6. Wire Logout
  const logoutBtn = document.getElementById("logoutBtn");
  if (logoutBtn) {
    logoutBtn.addEventListener("click", async () => {
      await logout();
      window.location.href = "login.html";
    });
  }

  // Initial Load (Default Tab)
  loadVideos();
}

// --- DATA LOADING FUNCTIONS ---

async function loadVideos() {
  const videos = await authedFetch("/videos");
  const list = document.getElementById("videoList");
  if (!videos || !videos.length) {
    const emptyState = document.getElementById("emptyState");
    if (emptyState) emptyState.style.display = "block";
    return;
  }
  const emptyState = document.getElementById("emptyState");
  if (emptyState) emptyState.style.display = "none";
  
  list.innerHTML = videos.map(v => `
    <li>
      <a class="video-row" style="color: var(--text-main);" href="video.html?id=${v.id}">
        <div>
          <div class="video-row-title">${v.title}</div>
          <div class="video-row-meta" style="color: var(--text-muted);">${new Date(v.created_at).toLocaleDateString()}</div>
        </div>
        <span class="status-chip ${v.status}">${v.status}</span>
      </a>
    </li>`).join("");
}

async function loadDocuments() {
  const docs = await authedFetch("/documents");
  const dropdown = document.getElementById("docSelectDropdown");
  if (dropdown) {
    dropdown.innerHTML = `<option value="">-- Choose uploaded document --</option>` + 
      docs.map(d => `<option value="${d.id}">${d.title}</option>`).join("");

    dropdown.onchange = (e) => {
      const docId = e.target.value;
      const selected = docs.find(d => d.id === docId);
      if (selected) {
        const viewer = document.getElementById("pdfViewerCanvas");
        if (viewer) {
          viewer.innerHTML = `<iframe src="https://notecast-web.onrender.com/media/${selected.storage_key}" style="width:100%; height:100%; border:none;"></iframe>`;
        }
        const editor = document.getElementById("docSummaryEditor");
        if (editor) {
          editor.value = selected.ai_summary_md || "Summary is generating in the background...";
          editHistory = [editor.value];
        }
      }
    };
  }
}

// --- FLASHCARD ENGINE (SM-2) ---
async function loadFlashcards() {
  dueFlashcards = await authedFetch("/flashcards/due");
  currentFcIndex = 0;
  renderCurrentFlashcard();
}

function renderCurrentFlashcard() {
  const emptyState = document.getElementById("fcEmptyState");
  const activeState = document.getElementById("fcActiveState");

  if (!dueFlashcards || currentFcIndex >= dueFlashcards.length) {
    if (emptyState) emptyState.style.display = "block";
    if (activeState) activeState.style.display = "none";
    return;
  }

  if (emptyState) emptyState.style.display = "none";
  if (activeState) activeState.style.display = "block";
  
  const card = dueFlashcards[currentFcIndex];
  document.getElementById("fcFront").textContent = card.front_text;
  document.getElementById("fcBack").textContent = card.back_text;
  
  document.getElementById("fcBack").style.display = "none";
  document.getElementById("fcControls").style.display = "none";
  document.getElementById("fcShowBtn").style.display = "block";
}


// --- KNOWLEDGE GRAPH ENGINE ---
async function loadGraph() {
  const graphData = await authedFetch("/graph");
  
  // Pull colors dynamically from CSS variables to match active theme
  const style = getComputedStyle(document.documentElement);
  const nodeBg = style.getPropertyValue('--graph-node-bg').trim();
  const nodeBorder = style.getPropertyValue('--graph-node-border').trim();
  const edgeColor = style.getPropertyValue('--graph-edge').trim();
  const textColor = style.getPropertyValue('--graph-text').trim();

  const nodes = new vis.DataSet(graphData.nodes.map(n => ({
    id: n.id,
    label: n.concept_name,
    title: n.description_md,
    color: { background: nodeBg, border: nodeBorder },
    font: { color: textColor }
  })));

  const edges = new vis.DataSet(graphData.edges.map(e => ({
    from: e.source_node_id,
    to: e.target_node_id,
    label: e.relationship_type.replace("_", " "),
    color: edgeColor,
    font: { color: edgeColor, size: 10, align: 'middle' },
    arrows: 'to'
  })));

  const container = document.getElementById("networkGraph");
  if (container) {
    const data = { nodes, edges };
    const options = {
      physics: {
        solver: 'forceAtlas2Based',
        forceAtlas2Based: { gravitationalConstant: -50, centralGravity: 0.01, springLength: 100 }
      },
      nodes: { shape: 'dot', size: 16, borderWidth: 2 },
      edges: { smooth: true },
      interaction: { hover: true, zoomView: true }
    };

    if (networkGraph) networkGraph.destroy();
    networkGraph = new vis.Network(container, data, options);
  }
}

init();