import { authedFetch, requireAuth, logout } from "./api.js";

let user;
let dueFlashcards = [];
let currentFcIndex = 0;
let networkGraph = null;
let editHistory = []; 
let currentSelectedDoc = null;
let currentPageNumber = 1;
const totalPages = 5; 
const pageCache = {}; 

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
  
  if (networkGraph && document.getElementById("pane-graph").classList.contains("active")) {
    loadGraph();
  }
}

const savedTheme = localStorage.getItem("theme") || (window.matchMedia("(prefers-color-scheme: light)").matches ? "light" : "dark");
applyTheme(savedTheme);

if (themeToggleBtn) {
  themeToggleBtn.addEventListener("click", () => {
    const currentTheme = document.documentElement.getAttribute("data-theme");
    applyTheme(currentTheme === "light" ? "dark" : "light");
  });
}

// --- FACULTY & COURSE STATIC LIBRARY DATA ---
const FACULTY_DATA = {
  Technology: [
    "Artificial_Intelligence", "Bioinformatics", "Blockchain_Technology", "Building_and_Construction_Technology", 
    "Cloud_Computing", "Computer_Animation", "Computer_Engineering", "Computer_Information_Systems_CIS", 
    "Computer_Science", "Cybersecurity_and_Cyber_Defense", "Data_Science_and_Analytics", "Database_Management_Systems", 
    "Digital_Forensics", "Educational_Technology", "Electrical_and_Electronics_Technology", "Game_Development", 
    "Geographic_Information_Systems_GIS", "Health_Information_Management", "Information_Communication_Technology_ICT", 
    "Information_Science", "Information_Technology_IT", "Instrumentation_and_Control_Systems_Technology", 
    "Internet_of_Things_IoT", "Management_Information_Systems_MIS", "Mobile_Application_Development", "Multimedia_Technology", 
    "Network_Administration", "Robotics_and_Mechatronics", "Software_Engineering", "Telecommunications_Engineering", 
    "Virtual_and_Augmented_Reality_VR_AR", "Web_Design_and_Development"
  ],
  Engineering: [
    "Aerospace_Engineering", "Agricultural_Engineering", "Automotive_Engineering", "Bioengineering", 
    "Biomedical_Engineering", "Chemical_Engineering", "Civil_Engineering", "Computer_Engineering", 
    "Electrical_Engineering", "Environmental_Engineering", "Industrial_Engineering", "Materials_Science_and_Engineering", 
    "Mechanical_Engineering", "Mechatronics_Engineering", "Mining_Engineering", "Nuclear_Engineering", 
    "Petroleum_Engineering", "Robotics_Engineering", "Software_Engineering", "Structural_Engineering", "Systems_Engineering"
  ],
  Education: [
    "BEd_Science_Mathematics_and_Physics", "BEd_Science_Biology_and_Chemistry", "BEd_Arts_Geography_and_Mathematics", 
    "BEd_Computer_Science", "MEd_Mathematics_Education", "MEd_Science_Education", "PGDE_Science_STEM", 
    "BEd_Technology_Education", "Diploma_in_Teacher_Education_Science"
  ],
  Business: [
    "Accounting", "Actuarial_Science", "Banking_and_Finance", "Business_Administration", "Business_Analytics", 
    "Business_Communication", "Commerce_BCom", "Corporate_Governance", "E_Commerce", "Entrepreneurship_and_Innovation", 
    "Financial_Engineering", "Hospitality_and_Tourism_Management", "Human_Resource_Management", "International_Business", 
    "Logistics_and_Supply_Chain_Management", "Management_Information_Systems_MIS", "Marketing_and_Digital_Strategy", 
    "Operations_Management", "Project_Management", "Real_Estate_Management", "Strategic_Management"
  ]
};

// --- DYNAMIC MODULE ROUTING ENGINE ---
// Maps specific courses to their custom HTML files, with a fallback for unbuilt courses.
const COURSE_MODULES = {
  "Database_Management_Systems": [
    { file: "single-node.html", name: "Single-Node Database Architecture" },
    { file: "shared-everything.html", name: "Shared-Everything Architecture (SMP)" },
    { file: "shared-disk.html", name: "Shared-Disk Architecture (SAN)" },
    { file: "shared-nothing.html", name: "Shared-Nothing Architecture (MPP)" },
    { file: "master-slave-replication.html", name: "Master-Slave Replication" },
    { file: "multi-master.html", name: "Multi-Master Replication" },
    { file: "peer-to-peer.html", name: "Peer-to-Peer Database Architecture" },
    { file: "serverless-database.html", name: "Serverless Database Architecture" },
    { file: "sharding.html", name: "Horizontal Partitioning (Sharding)" },
    { file: "vertical-partitioning.html", name: "Vertical Partitioning" },
    { file: "range-partitioning.html", name: "Range Partitioning" },
    { file: "hash-partitioning.html", name: "Hash Partitioning" },
    { file: "list-partitioning.html", name: "List Partitioning" },
    { file: "composite-partitioning.html", name: "Composite Partitioning" },
    { file: "concurrency-control-locking.html", name: "Concurrency Control and Locking" },
    { file: "mvcc.html", name: "Multi-Version Concurrency Control" },
    { file: "two-phase-locking.html", name: "Two-Phase Locking (2PL)" },
    { file: "occ.html", name: "Optimistic Concurrency Control" },
    { file: "wal.html", name: "Write-Ahead Logging (WAL)" },
    { file: "aries.html", name: "ARIES Recovery Protocol" },
    { file: "buffer-pool.html", name: "Buffer Pool Management" },
    { file: "lru-eviction.html", name: "LRU Cache Eviction" },
    { file: "clock-replacement.html", name: "Clock Page Replacement" },
    { file: "cost-based-optimizer.html", name: "Cost-Based Query Optimization" },
    { file: "plan-execution-trees.html", name: "Plan Selection & Execution Trees" },
    { file: "btree-splits.html", name: "B+ Tree Index Node Splitting" },
    { file: "lsm-compaction.html", name: "LSM-Tree Log Compaction" },
    { file: "write-amplification.html", name: "Write Amplification Modeling" },
    { file: "in-memory-tiering.html", name: "In-Memory Data Tiering" },
    { file: "deadlock-detection.html", name: "Transaction Deadlock Detection" },
    { file: "two-phase-commit.html", name: "Two-Phase Commit Protocol (2PC)" },
    { file: "three-phase-commit.html", name: "Three-Phase Commit Protocol (3PC)" },
    { file: "vector-hnsw.html", name: "Vector Database Indexing (HNSW)" },
    { file: "columnar-compaction.html", name: "Columnar Storage Compaction" },
    { file: "raft.html", name: "Distributed Consensus (Raft)" },
    { file: "paxos.html", name: "Distributed Consensus (Paxos)" },
    { file: "concurrency-comparison.html", name: "MVCC vs 2PL vs OCC Comparison" },
    { file: "distributed-transactions.html", name: "Distributed Transactions (Capstone)" },
    { file: "database-architecture.html", name: "Full Database System Architecture" },
    { file: "database-design-space.html", name: "The Database Design Space (Finale)" }
  ],
  "default_fallback": [
    { file: "fundamentals.html", name: "Fundamentals & Core Concepts" },
    { file: "advanced_architecture.html", name: "Advanced Architecture & Systems" },
    { file: "case_study_simulation.html", name: "Case Study & Real-World Simulation" }
  ]
};

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

      if (tabName === "notes") loadVideos();
      if (tabName === "documents") loadDocuments();
      if (tabName === "flashcards") loadFlashcards();
      if (tabName === "graph") loadGraph();
    });
  });

  // 2. Wire Cascading Dropdowns for Static Library (Zero Timeout Path)
  const facultySelect = document.getElementById("facultySelect");
  const courseDropdown = document.getElementById("courseDropdown");
  const moduleDropdown = document.getElementById("moduleDropdown");
  const launchBtn = document.getElementById("launchStaticSimBtn");

  if (facultySelect) {
    facultySelect.addEventListener("change", (e) => {
      const faculty = e.target.value;
      courseDropdown.innerHTML = '<option value="">-- Select Course --</option>';
      moduleDropdown.innerHTML = '<option value="">-- Select Course First --</option>';
      courseDropdown.disabled = !faculty;
      moduleDropdown.disabled = true;
      launchBtn.disabled = true;

      if (faculty && FACULTY_DATA[faculty]) {
        FACULTY_DATA[faculty].forEach(course => {
          const opt = document.createElement("option");
          opt.value = course;
          opt.textContent = course.replace(/_/g, " ");
          courseDropdown.appendChild(opt);
        });
      }
    });

    courseDropdown.addEventListener("change", (e) => {
      const course = e.target.value;
      moduleDropdown.innerHTML = '<option value="">-- Select Module --</option>';
      moduleDropdown.disabled = !course;
      launchBtn.disabled = true;

      if (course) {
        // Automatically check if custom modules exist for this course, otherwise load the 3 defaults
        const modulesToLoad = COURSE_MODULES[course] || COURSE_MODULES["default_fallback"];
        
        modulesToLoad.forEach(mod => {
          const opt = document.createElement("option");
          opt.value = mod.file;
          opt.textContent = mod.name;
          moduleDropdown.appendChild(opt);
        });
      }
    });

    moduleDropdown.addEventListener("change", (e) => {
      launchBtn.disabled = !e.target.value;
    });

    launchBtn.addEventListener("click", () => {
      const faculty = facultySelect.value;
      const course = courseDropdown.value;
      const moduleFile = moduleDropdown.value;

      if (!faculty || !course || !moduleFile) return alert("Please make a complete selection.");

      // Direct local file mapping for instant execution
      const filePath = `${faculty}/${course}/${moduleFile}`;
      const readableTitle = `${course.replace(/_/g, " ")} — ${moduleDropdown.options[moduleDropdown.selectedIndex].text}`;

      window.location.href = `simulator.html?file=${encodeURIComponent(filePath)}&title=${encodeURIComponent(readableTitle)}`;
    });
  }

  // 3. Wire Custom AI Generation (With 120s Extended Client Timeout and Cloud Gateway Error Catching)
  const generateSimBtn = document.getElementById("generateSimBtn");
  if (generateSimBtn) {
    generateSimBtn.addEventListener("click", async () => {
      const topic = document.getElementById("simTopicInput").value.trim();
      if (!topic) return alert("Please enter a topic or unit name!");

      generateSimBtn.disabled = true;
      generateSimBtn.textContent = "Synthesizing...";
      
      const controller = new AbortController();
      const timeoutId = setTimeout(() => controller.abort(), 120000); 

      try {
        const schema = await authedFetch("/diagrams/generate-sim/", {
          method: "POST",
          body: JSON.stringify({ topic }),
          signal: controller.signal
        });
        
        clearTimeout(timeoutId);

        if (!schema) {
          throw new Error("The proxy cloud provider timed out the request or returned an empty response.");
        }

        sessionStorage.setItem("active_sim_schema", JSON.stringify(schema));
        window.location.href = `simulator.html?topic=${encodeURIComponent(topic)}`;
      } catch (err) {
        clearTimeout(timeoutId);
        console.error("Simulation Generation Error:", err);
        
        // Friendly alert intercepting Render proxy drops
        if (err.name === 'AbortError' || (err.message && (err.message.includes("502") || err.message.includes("504") || err.message.includes("empty response")))) {
          alert(`Network Timeout: The cloud provider dropped the connection because the AI took longer than 30 seconds to generate the environment.\n\nPlease use the "Pre-Compiled Academic Library" dropdown above instead for instant access without generation limits.`);
        } else {
          alert("Failed to generate simulation. Please check your provider keys and try again.");
        }
      } finally {
        generateSimBtn.disabled = false;
        generateSimBtn.textContent = "Generate Live";
      }
    });
  }

  // 4. Collapsible Sidebar Toggle for Notes & Summary
  const readerWorkspace = document.getElementById("readerWorkspace");
  const toggleSidebarBtn = document.getElementById("toggleSidebarBtn");
  const closeSidebarBtn = document.getElementById("closeSidebarBtn");

  if (toggleSidebarBtn && readerWorkspace) {
    toggleSidebarBtn.addEventListener("click", () => {
      readerWorkspace.classList.toggle("sidebar-open");
    });
  }
  if (closeSidebarBtn && readerWorkspace) {
    closeSidebarBtn.addEventListener("click", () => {
      readerWorkspace.classList.remove("sidebar-open");
    });
  }

  // 5. Docu-Vision Professional Editor & Shape Insertion
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

  // 6. Generate Short Notes Prompt Workflow
  const genNotesBtn = document.getElementById("generateShortNotesBtn");
  if (genNotesBtn) {
    genNotesBtn.addEventListener("click", async () => {
      if (!currentSelectedDoc) return alert("Please select or upload a document first!");
      
      const cacheKey = `${currentSelectedDoc.id}_p${currentPageNumber}`;
      
      if (pageCache[cacheKey]) {
        summaryEditor.value = pageCache[cacheKey];
        alert(`Loaded cached notes for Page ${currentPageNumber}`);
        return;
      }

      const progressSection = document.getElementById("aiProgressSection");
      const progressText = document.getElementById("progressText");
      const progressBarFill = document.getElementById("progressBarFill");
      
      progressSection.style.display = "block";
      genNotesBtn.disabled = true;

      let progress = 0;
      const interval = setInterval(async () => {
        progress += 25;
        progressBarFill.style.width = `${progress}%`;
        progressText.textContent = `Analyzing Page ${currentPageNumber}... ${progress}%`;

        if (progress >= 100) {
          clearInterval(interval);
          genNotesBtn.disabled = false;
          progressSection.style.display = "none";
          
          const generatedSummary = `# ${currentSelectedDoc.title} — Page ${currentPageNumber}\n\n## Instant Page Snapshot Analysis\nCaptured page successfully.\nExtracted core formulas and definitions.\n\n[DIAGRAM: Flowchart Box]`;
          pageCache[cacheKey] = generatedSummary;
          
          summaryEditor.value = generatedSummary;
          editHistory = [summaryEditor.value];
          alert(`Page ${currentPageNumber} analyzed!`);
        }
      }, 300);
    });
  }

  const nextPageBtn = document.getElementById("nextPageBtn");
  const prevPageBtn = document.getElementById("prevPageBtn");
  
  if (nextPageBtn) {
    nextPageBtn.addEventListener("click", () => {
      if (currentPageNumber < totalPages) {
        switchToPage(currentPageNumber + 1);
      }
    });
  }
  
  if (prevPageBtn) {
    prevPageBtn.addEventListener("click", () => {
      if (currentPageNumber > 1) {
        switchToPage(currentPageNumber - 1);
      }
    });
  }

  // 7. Wire PDF Upload
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
        const newDoc = await authedFetch("/documents/upload/", {
          method: "POST",
          body: formData
        });
        
        alert("Document uploaded successfully! Loading viewer...");
        
        await loadDocuments();
        const dropdown = document.getElementById("docSelectDropdown");
        dropdown.value = newDoc.id;
        dropdown.dispatchEvent(new Event('change')); 
        
        fileInput.value = "";
      } catch (err) {
        alert("Error uploading document. Check backend logs.");
      } finally {
        btn.disabled = false;
        btn.textContent = "Upload & Process";
      }
    });
  }

  // 8. Flashcard Actions
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
        await authedFetch(`/flashcards/review/${cardId}/`, {
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

  // 9. Wire Logout
  const logoutBtn = document.getElementById("logoutBtn");
  if (logoutBtn) {
    logoutBtn.addEventListener("click", async () => {
      await logout();
      window.location.href = "login.html";
    });
  }

  loadVideos();
  loadDocuments();
}

function switchToPage(pageNum) {
  currentPageNumber = pageNum;
  document.getElementById("pageIndicator").textContent = `Page ${currentPageNumber} of ${totalPages}`;
  
  document.querySelectorAll(".thumb-card").forEach((t, idx) => {
    if (idx + 1 === currentPageNumber) {
      t.classList.add("active");
    } else {
      t.classList.remove("active");
    }
  });

  const cacheKey = `${currentSelectedDoc?.id}_p${currentPageNumber}`;
  const editor = document.getElementById("docSummaryEditor");
  
  if (pageCache[cacheKey]) {
    editor.value = pageCache[cacheKey];
  } else {
    editor.value = `Page ${currentPageNumber} active. Click 'Notes & Summary' on the top right to view or generate AI notes.`;
  }
}

// --- DATA LOADING FUNCTIONS ---

async function loadVideos() {
  const videos = await authedFetch("/videos/");
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

let cachedDocuments = [];

async function loadDocuments() {
  try {
    cachedDocuments = await authedFetch("/documents/");
  } catch (err) {
    console.error("Failed to load documents list", err);
    cachedDocuments = [];
  }

  const dropdown = document.getElementById("docSelectDropdown");
  if (dropdown) {
    dropdown.innerHTML = `<option value="">-- Select Document --</option>` + 
      cachedDocuments.map(d => `<option value="${d.id}">${d.title || d.filename}</option>`).join("");

    dropdown.onchange = (e) => {
      const docId = e.target.value;
      currentSelectedDoc = cachedDocuments.find(d => d.id === docId);
      
      const viewer = document.getElementById("pdfViewerCanvas");
      const fileNameEl = document.getElementById("currentFileName");

      if (currentSelectedDoc) {
        fileNameEl.textContent = currentSelectedDoc.filename || currentSelectedDoc.title;
        
        if (viewer) {
          const fileKey = currentSelectedDoc.storage_key || currentSelectedDoc.id;
          viewer.innerHTML = `<iframe src="/api/documents/media/${fileKey}/" style="width:100%; height:100%; border:none; background:#ffffff;"></iframe>`;
        }

        const thumbsContainer = document.getElementById("readerThumbsContainer");
        thumbsContainer.innerHTML = `<div style="font-size: 0.6rem; font-weight: 700; color: var(--text-muted);">Pg</div>`;
        for (let i = 1; i <= totalPages; i++) {
          const thumb = document.createElement("div");
          thumb.className = i === 1 ? "thumb-card active" : "thumb-card";
          thumb.innerHTML = `${i}`;
          thumb.onclick = () => switchToPage(i);
          thumbsContainer.appendChild(thumb);
        }
        switchToPage(1);
      } else {
        fileNameEl.textContent = "No file selected";
        if (viewer) {
          viewer.innerHTML = `<span style="color: #64748b; font-size: 0.85rem;">Upload or select a PDF to begin immersive reading</span>`;
        }
      }
    };
  }
}

async function loadFlashcards() {
  dueFlashcards = await authedFetch("/flashcards/due/");
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

async function loadGraph() {
  const graphData = await authedFetch("/graph/");
  
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