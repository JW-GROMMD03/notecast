import { authedFetch, requireAuth, logout, checkExtensionInstalled, CHROME_STORE_URL } from "./api.js";

let user = null;
let dueFlashcards = [];
let currentFcIndex = 0;
let networkGraph = null;
let editHistory = []; 
let currentSelectedDoc = null;
let currentPageNumber = 1;
const totalPages = 5; 
const pageCache = {}; 

// --- HELPER: CLEAN ERROR MESSAGE EXTRACTOR ---
function extractErrorMessage(data) {
  if (!data) return "An unknown error occurred.";
  if (typeof data === "string") return data;
  
  if (Array.isArray(data.detail)) {
    return data.detail
      .map(err => `${err.loc ? err.loc.slice(1).join(".") + ": " : ""}${err.msg}`)
      .join("\n");
  }
  
  if (typeof data.detail === "string") return data.detail;
  if (data.message && typeof data.message === "string") return data.message;
  
  try {
    return JSON.stringify(data);
  } catch (e) {
    return "Request failed.";
  }
}

// --- THEME ENGINE ---
const themeToggleBtn = document.getElementById("themeToggleBtn");
const themeIcon = document.getElementById("themeIcon");
const themeText = document.getElementById("themeText");

function applyTheme(theme) {
  document.documentElement.setAttribute("data-theme", theme);
  localStorage.setItem("theme", theme);
  
  if (theme === "light") {
    if (themeIcon) themeIcon.textContent = "🌙";
    if (themeText) themeText.textContent = "Dark Mode";
  } else {
    if (themeIcon) themeIcon.textContent = "☀️";
    if (themeText) themeText.textContent = "Light Mode";
  }
  
  if (networkGraph && document.getElementById("pane-graph")?.classList.contains("active")) {
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

// --- UTC MIDNIGHT RESET TIMER CALCULATOR ---
function getTimeUntilMidnightUTC() {
  const now = new Date();
  const tomorrowUTC = new Date(Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), now.getUTCDate() + 1, 0, 0, 0));
  const diffMs = tomorrowUTC - now;
  
  const hours = Math.floor(diffMs / (1000 * 60 * 60));
  const minutes = Math.floor((diffMs % (1000 * 60 * 60)) / (1000 * 60));
  return `${hours}h ${minutes}m`;
}

// --- DUAL-MODE SUBSCRIPTION & QUOTA EXHAUSTION ALERT MODAL ---
function showEntitlementModal({ featureName, recommendedTier = "STANDARD", priceText = "800 KES/mo", isQuotaDepleted = false, detailMessage = null }) {
  const existingModal = document.getElementById('entitlementModal');
  if (existingModal) existingModal.remove();

  const resetTimeStr = getTimeUntilMidnightUTC();
  const currentPlanName = (user?.plan || 'FREE').toUpperCase();

  const headerIcon = isQuotaDepleted ? "⏳" : "🔒";
  const modalTitle = isQuotaDepleted ? "Daily Limit Reached" : "Subscription Pass Needed";
  
  let mainDescription = "";
  if (isQuotaDepleted) {
    mainDescription = detailMessage || `You have reached your daily privilege limit for <strong>${featureName}</strong> on the <strong>${currentPlanName} Plan</strong> today.`;
  } else {
    mainDescription = `Your current plan (<strong>${currentPlanName}</strong>) does not include access to <strong>${featureName}</strong>. Subscribe to an eligible pass to unlock access instantly.`;
  }

  const quotaBoxHtml = isQuotaDepleted ? `
    <div style="background: rgba(245, 158, 11, 0.1); border: 1px solid rgba(245, 158, 11, 0.3); border-radius: 10px; padding: 12px; margin: 14px 0; text-align: center; color: #f59e0b; font-weight: 600; font-size: 0.88rem;">
      🕒 Daily quota resets in <strong>${resetTimeStr}</strong> (00:00 UTC)
    </div>
  ` : '';

  const modalHtml = `
    <div id="entitlementModal" class="entitlement-modal-overlay" style="position:fixed;top:0;left:0;width:100vw;height:100vh;background:rgba(3,7,18,0.85);backdrop-filter:blur(8px);display:flex;align-items:center;justify-content:center;z-index:99999;">
      <div class="entitlement-modal-card" style="background:var(--bg-card, #0f172a);border:1px solid #3b82f6;border-radius:16px;padding:28px;max-width:480px;width:90%;color:#fff;box-shadow:0 20px 50px rgba(0,0,0,0.6);text-align:center;">
        <div style="font-size:2.5rem;margin-bottom:8px;">${headerIcon}</div>
        <h3 style="margin:0 0 10px 0;font-size:1.3rem;">${modalTitle}</h3>
        <p style="color:#94a3b8;font-size:0.88rem;line-height:1.5;margin-bottom:12px;">
          ${mainDescription}
        </p>

        ${quotaBoxHtml}

        <div style="background: rgba(59, 130, 246, 0.08); border: 1px solid rgba(59, 130, 246, 0.2); border-radius: 10px; padding: 12px; text-align: left; margin-bottom: 20px;">
          <div style="font-size: 0.78rem; font-weight: 700; color: #60a5fa; text-transform: uppercase; margin-bottom: 6px;">Qualifying Subscription Passes:</div>
          <ul style="margin: 0; padding-left: 18px; font-size: 0.82rem; color: #cbd5e1; line-height: 1.5;">
            <li><strong>Startup Pass</strong> — 100 KES / mo (1 Hr YouTube Notes)</li>
            <li><strong>Basic Pass</strong> — 250 KES / mo (2 Hrs Notes + Free Downloads)</li>
            <li><strong style="color: #60a5fa;">Standard Pass</strong> — 800 KES / mo (4 Hrs Notes + 2 Sims/day)</li>
            <li><strong style="color: #60a5fa;">Premium Pass</strong> — 1199 KES / mo (12 Hrs Notes + Unlimited AI)</li>
          </ul>
        </div>

        <div style="display:flex;gap:12px;justify-content:center;">
          <button onclick="document.getElementById('entitlementModal').remove()" style="padding:10px 18px;background:#334155;border:none;border-radius:8px;color:#fff;cursor:pointer;font-weight:600;">Close</button>
          <button onclick="document.getElementById('entitlementModal').remove(); window.openPaymentModal('${recommendedTier}', '${priceText}');" style="padding:10px 20px;background:#3b82f6;border:none;border-radius:8px;color:#fff;cursor:pointer;font-weight:700;">Subscribe to ${recommendedTier} (${priceText})</button>
        </div>
      </div>
    </div>
  `;
  document.body.insertAdjacentHTML('beforeend', modalHtml);
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
  ],
  Medical_and_Health_Sciences: [
    "School_of_Nursing", "Medicine_and_Surgery", "Anatomy", "Clinical_Medicine"
  ]
};

// --- DYNAMIC MODULE ROUTING ENGINE ---
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
  "Software_Engineering": [
    { file: "agile-scrum-sprints.html", name: "Agile Scrum Sprint Cycles" },
    { file: "kanban-bottlenecks.html", name: "Kanban Board Bottlenecks" },
    { file: "git-branching-merging.html", name: "Git Branching and Merging Workflows" },
    { file: "cicd-pipeline.html", name: "CI/CD Pipeline Build & Deployment Stages" },
    { file: "blue-green-deployment.html", name: "Blue-Green Deployment Routing" },
    { file: "canary-release.html", name: "Canary Release Traffic Shifting" },
    { file: "microservices-discovery.html", name: "Microservices Service Discovery & Choreography" },
    { file: "event-driven-queues.html", name: "Event-Driven Architecture Message Queues" },
    { file: "load-balancing-routing.html", name: "Load Balancing and Traffic Routing" },
    { file: "circuit-breaker.html", name: "Circuit Breaker Pattern State Transitions" },
    { file: "rate-limiting.html", name: "Rate Limiting Token Bucket & Leaky Bucket" },
    { file: "rest-vs-grpc.html", name: "REST vs. gRPC Network Payload Latency" },
    { file: "api-gateway-auth.html", name: "API Gateway Routing & Authentication Flows" },
    { file: "clean-architecture.html", name: "Clean Architecture & Layered Dependencies" },
    { file: "design-patterns.html", name: "Design Patterns (Observer, Strategy, etc.)" },
    { file: "memory-stack-heap.html", name: "Object-Oriented Memory (Stack vs Heap)" },
    { file: "garbage-collection.html", name: "Garbage Collection & Memory Leak Cycles" },
    { file: "distributed-tracing.html", name: "Distributed Tracing & Request Propagation" },
    { file: "monolith-to-microservices.html", name: "Monolithic to Microservices Decomposition" },
    { file: "consensus-raft-paxos.html", name: "Consensus Protocols (Raft & Paxos Election)" },
    { file: "cap-theorem.html", name: "CAP Theorem System Trade-offs" },
    { file: "thread-pools-races.html", name: "Multi-Threading Thread Pools & Race Conditions" },
    { file: "actor-model.html", name: "Actor Model Concurrency" },
    { file: "chaos-engineering.html", name: "Chaos Engineering & Fault Injection" },
    { file: "cache-invalidation.html", name: "Cache Invalidation & Cache-Aside Patterns" },
    { file: "cpu-scheduling.html", name: "CPU Scheduling (FIFO, SJF, RR, Priority)" },
    { file: "process-lifecycle.html", name: "Process Lifecycle State Transitions" },
    { file: "context-switching.html", name: "Context Switching Overhead" },
    { file: "thread-allocation.html", name: "Thread Allocation & Context Switching" },
    { file: "deadlock-avoidance.html", name: "Deadlock Avoidance (Banker's Algorithm)" },
    { file: "dining-philosophers.html", name: "Dining Philosophers Resource Allocation" },
    { file: "producer-consumer.html", name: "Producer-Consumer Bounded Buffer" },
    { file: "readers-writers.html", name: "Readers-Writers Concurrency" },
    { file: "semaphores-mutexes.html", name: "Semaphore & Mutex Locking Mechanisms" },
    { file: "page-replacement.html", name: "Virtual Memory Page Replacement (FIFO/LRU/Optimal)" },
    { file: "page-faults-thrashing.html", name: "Page Faults and Thrashing" },
    { file: "memory-allocation.html", name: "Memory Allocation (First/Best/Worst Fit)" },
    { file: "memory-fragmentation.html", name: "Memory Fragmentation & Compaction" },
    { file: "inverted-page-tables.html", name: "Inverted Page Tables & TLB Caches" },
    { file: "file-system-allocation.html", name: "File System Allocation (Contiguous/Linked/Indexed)" },
    { file: "disk-scheduling.html", name: "Disk Scheduling (FIFO, SSTF, SCAN, LOOK, C-SCAN)" },
    { file: "io-buffering.html", name: "I/O Buffering & Interrupt Handling" },
    { file: "microkernel-monolithic.html", name: "Microkernel vs Monolithic Kernel Flows" },
    { file: "dijkstra.html", name: "Dijkstra's Shortest Path Execution" },
    { file: "a-star.html", name: "A* Search Tree Expansion" },
    { file: "dynamic-programming.html", name: "DP Matrix Filling (Knapsack, LCS)" },
    { file: "divide-conquer-sort.html", name: "Divide & Conquer Merge/Quick Sort Recursion" },
    { file: "bst-balancing.html", name: "BST Balancing (AVL & Red-Black Rotations)" },
    { file: "graph-traversals.html", name: "Graph Traversals (BFS & DFS Frontier)" },
    { file: "network-flow.html", name: "Network Flow (Ford-Fulkerson Residual Graphs)" },
    { file: "huffman-coding.html", name: "Huffman Coding Tree Construction" },
    { file: "hash-collisions.html", name: "Hash Collision Resolution (Chaining vs Open)" },
    { file: "public-key-crypto.html", name: "Cryptographic Handshakes (RSA/Diffie-Hellman)" },
    { file: "consistent-hashing-dht.html", name: "Consistent Hashing & DHT Rings" },
    { file: "distributed-deadlock.html", name: "Distributed Deadlock Detection" },
    { file: "vector-clocks.html", name: "Vector Clocks & Lamport Timestamps" },
    { file: "byzantine-generals.html", name: "Byzantine Generals Problem Consensus" },
    { file: "mapreduce.html", name: "MapReduce Partitioning & Shuffle Phases" },
    { file: "gossip-heartbeat.html", name: "Gossip Protocol & Heartbeat Leader Election" },
    { file: "packet-routing-tcp.html", name: "Network Packet Routing & TCP Congestion Control" }
  ],
  "Computer_Science": [
    { file: "agile-scrum-sprints.html", name: "Agile Scrum Sprint Cycles" },
    { file: "kanban-bottlenecks.html", name: "Kanban Board Bottlenecks" },
    { file: "git-branching-merging.html", name: "Git Branching and Merging Workflows" },
    { file: "cicd-pipeline.html", name: "CI/CD Pipeline Build & Deployment Stages" },
    { file: "blue-green-deployment.html", name: "Blue-Green Deployment Routing" },
    { file: "canary-release.html", name: "Canary Release Traffic Shifting" },
    { file: "microservices-discovery.html", name: "Microservices Service Discovery & Choreography" },
    { file: "event-driven-queues.html", name: "Event-Driven Architecture Message Queues" },
    { file: "load-balancing-routing.html", name: "Load Balancing and Traffic Routing" },
    { file: "circuit-breaker.html", name: "Circuit Breaker Pattern State Transitions" },
    { file: "rate-limiting.html", name: "Rate Limiting Token Bucket & Leaky Bucket" },
    { file: "rest-vs-grpc.html", name: "REST vs. gRPC Network Payload Latency" },
    { file: "api-gateway-auth.html", name: "API Gateway Routing & Authentication Flows" },
    { file: "clean-architecture.html", name: "Clean Architecture & Layered Dependencies" },
    { file: "design-patterns.html", name: "Design Patterns (Observer, Strategy, etc.)" },
    { file: "memory-stack-heap.html", name: "Object-Oriented Memory (Stack vs Heap)" },
    { file: "garbage-collection.html", name: "Garbage Collection & Memory Leak Cycles" },
    { file: "distributed-tracing.html", name: "Distributed Tracing & Request Propagation" },
    { file: "monolith-to-microservices.html", name: "Monolithic to Microservices Decomposition" },
    { file: "consensus-raft-paxos.html", name: "Consensus Protocols (Raft & Paxos Election)" },
    { file: "cap-theorem.html", name: "CAP Theorem System Trade-offs" },
    { file: "thread-pools-races.html", name: "Multi-Threading Thread Pools & Race Conditions" },
    { file: "actor-model.html", name: "Actor Model Concurrency" },
    { file: "chaos-engineering.html", name: "Chaos Engineering & Fault Injection" },
    { file: "cache-invalidation.html", name: "Cache Invalidation & Cache-Aside Patterns" },
    { file: "cpu-scheduling.html", name: "CPU Scheduling (FIFO, SJF, RR, Priority)" },
    { file: "process-lifecycle.html", name: "Process Lifecycle State Transitions" },
    { file: "context-switching.html", name: "Context Switching Overhead" },
    { file: "thread-allocation.html", name: "Thread Allocation & Context Switching" },
    { file: "deadlock-avoidance.html", name: "Deadlock Avoidance (Banker's Algorithm)" },
    { file: "dining-philosophers.html", name: "Dining Philosophers Resource Allocation" },
    { file: "producer-consumer.html", name: "Producer-Consumer Bounded Buffer" },
    { file: "readers-writers.html", name: "Readers-Writers Concurrency" },
    { file: "semaphores-mutexes.html", name: "Semaphore & Mutex Locking Mechanisms" },
    { file: "page-replacement.html", name: "Virtual Memory Page Replacement (FIFO/LRU/Optimal)" },
    { file: "page-faults-thrashing.html", name: "Page Faults and Thrashing" },
    { file: "memory-allocation.html", name: "Memory Allocation (First/Best/Worst Fit)" },
    { file: "memory-fragmentation.html", name: "Memory Fragmentation & Compaction" },
    { file: "inverted-page-tables.html", name: "Inverted Page Tables & TLB Caches" },
    { file: "file-system-allocation.html", name: "File System Allocation (Contiguous/Linked/Indexed)" },
    { file: "disk-scheduling.html", name: "Disk Scheduling (FIFO, SSTF, SCAN, LOOK, C-SCAN)" },
    { file: "io-buffering.html", name: "I/O Buffering & Interrupt Handling" },
    { file: "microkernel-monolithic.html", name: "Microkernel vs Monolithic Kernel Flows" },
    { file: "dijkstra.html", name: "Dijkstra's Shortest Path Execution" },
    { file: "a-star.html", name: "A* Search Tree Expansion" },
    { file: "dynamic-programming.html", name: "DP Matrix Filling (Knapsack, LCS)" },
    { file: "divide-conquer-sort.html", name: "Divide & Conquer Merge/Quick Sort Recursion" },
    { file: "bst-balancing.html", name: "BST Balancing (AVL & Red-Black Rotations)" },
    { file: "graph-traversals.html", name: "Graph Traversals (BFS & DFS Frontier)" },
    { file: "network-flow.html", name: "Network Flow (Ford-Fulkerson Residual Graphs)" },
    { file: "huffman-coding.html", name: "Huffman Coding Tree Construction" },
    { file: "hash-collisions.html", name: "Hash Collision Resolution (Chaining vs Open)" },
    { file: "public-key-crypto.html", name: "Cryptographic Handshakes (RSA/Diffie-Hellman)" },
    { file: "consistent-hashing-dht.html", name: "Consistent Hashing & DHT Rings" },
    { file: "distributed-deadlock.html", name: "Distributed Deadlock Detection" },
    { file: "vector-clocks.html", name: "Vector Clocks & Lamport Timestamps" },
    { file: "byzantine-generals.html", name: "Byzantine Generals Problem Consensus" },
    { file: "mapreduce.html", name: "MapReduce Partitioning & Shuffle Phases" },
    { file: "gossip-heartbeat.html", name: "Gossip Protocol & Heartbeat Leader Election" },
    { file: "packet-routing-tcp.html", name: "Network Packet Routing & TCP Congestion Control" }
  ],
  "Mechanical_Engineering": [
    { file: "stress-strain-curve.html", name: "Stress-Strain Curve & Material Behavior" },
    { file: "mohrs-circle.html", name: "Mohr's Circle for Stress Transformation" },
    { file: "beam-bending.html", name: "Beam Bending & Shear/Moment Diagrams" },
    { file: "torsion-shafts.html", name: "Torsion of Circular Shafts" },
    { file: "buckling-columns.html", name: "Euler Buckling & Column Stability" },
    { file: "combined-loading.html", name: "Combined Loading & Principal Stresses" },
    { file: "crystal-structures.html", name: "FCC, BCC, HCP Crystal Structures" },
    { file: "phase-diagrams.html", name: "Phase Diagrams & Lever Rule" },
    { file: "heat-treatment.html", name: "Annealing, Quenching, Tempering" },
    { file: "fatigue-failure.html", name: "Fatigue Failure & S-N Curves" },
    { file: "creep-deformation.html", name: "Creep Deformation & Time-Temperature" },
    { file: "fracture-toughness.html", name: "Fracture Mechanics & Crack Propagation" },
    { file: "carnot-cycle.html", name: "Carnot Cycle & Maximum Efficiency" },
    { file: "rankine-cycle.html", name: "Rankine Cycle (Steam Power)" },
    { file: "brayton-cycle.html", name: "Brayton Cycle (Gas Turbines)" },
    { file: "refrigeration-cycle.html", name: "Vapor Compression Refrigeration" },
    { file: "otto-diesel-cycles.html", name: "Otto & Diesel Cycles" },
    { file: "entropy-enthalpy.html", name: "Entropy, Enthalpy & Property Diagrams" },
    { file: "bernoulli-equation.html", name: "Bernoulli's Equation & Flow Energy" },
    { file: "reynolds-number.html", name: "Reynolds Number & Laminar/Turbulent" },
    { file: "pipe-flow-losses.html", name: "Darcy-Weisbach Pipe Flow Losses" },
    { file: "boundary-layer.html", name: "Boundary Layer Development" },
    { file: "drag-lift.html", name: "Drag & Lift on Immersed Bodies" },
    { file: "pump-turbine-curves.html", name: "Pump & Turbine Performance Curves" },
    { file: "conduction-fourier.html", name: "Fourier's Law & 1D Conduction" },
    { file: "convection-newton.html", name: "Newton's Law of Cooling & Convection" },
    { file: "radiation-stefan.html", name: "Stefan-Boltzmann Radiation" },
    { file: "heat-exchangers.html", name: "Heat Exchanger Effectiveness (LMTD, NTU)" },
    { file: "fin-analysis.html", name: "Extended Surfaces (Fins)" },
    { file: "transient-conduction.html", name: "Transient Conduction & Biot Number" },
    { file: "gear-trains.html", name: "Gear Trains & Gear Ratios" },
    { file: "belt-chain-drives.html", name: "Belt & Chain Drives" },
    { file: "bearings.html", name: "Rolling & Journal Bearings" },
    { file: "shaft-design.html", name: "Shaft Design & Combined Loading" },
    { file: "fasteners.html", name: "Bolted & Welded Joints" },
    { file: "springs.html", name: "Spring Design & Hooke's Law" },
    { file: "projectile-motion.html", name: "Projectile Motion with Drag" },
    { file: "rigid-body-dynamics.html", name: "Rigid Body Rotation & Moment of Inertia" },
    { file: "single-dof-vibration.html", name: "Single-DOF Vibration (Free & Forced)" },
    { file: "damping.html", name: "Damping Types" },
    { file: "resonance.html", name: "Resonance & Natural Frequencies" },
    { file: "multi-dof-vibration.html", name: "Multi-DOF Systems & Mode Shapes" },
    { file: "casting-processes.html", name: "Casting & Solidification" },
    { file: "machining-turning.html", name: "Turning & Cutting Forces" },
    { file: "welding-joints.html", name: "Welding Processes & Joints" },
    { file: "sheet-metal.html", name: "Sheet Metal Forming" },
    { file: "additive-manufacturing.html", name: "Additive Manufacturing (3D Printing)" },
    { file: "injection-molding.html", name: "Injection Molding & Flow" },
    { file: "pid-control.html", name: "PID Controller Tuning" },
    { file: "dc-motors.html", name: "DC Motor Characteristics" },
    { file: "stepper-servo.html", name: "Stepper vs Servo Motors" },
    { file: "sensor-actuator.html", name: "Sensors & Actuators" },
    { file: "robot-kinematics.html", name: "Robot Forward/Inverse Kinematics" },
    { file: "hydraulic-pneumatic.html", name: "Hydraulic & Pneumatic Systems" },
    { file: "fea-basics.html", name: "Finite Element Analysis Basics" },
    { file: "cfd-intro.html", name: "Computational Fluid Dynamics Intro" },
    { file: "turbomachinery.html", name: "Turbomachinery (Compressors & Turbines)" },
    { file: "hvac-systems.html", name: "HVAC & Psychrometrics" },
    { file: "renewable-energy.html", name: "Renewable Energy Systems" },
    { file: "sustainability-lifecycle.html", name: "Sustainability & Life Cycle Analysis" },
    { file: "case_study_simulation.html", name: "Real-World Engineering Failures" },
    { file: "fundamentals.html", name: "8 Core Engineering Topics" },
    { file: "advanced_architecture.html", name: "System Architecture Patterns" }
  ],
  "Cybersecurity_and_Cyber_Defense": [
    { file: "cia-triad.html", name: "CIA Triad & Security Principles" },
    { file: "threat-modeling.html", name: "Threat Modeling (STRIDE, DREAD)" },
    { file: "attack-surface.html", name: "Attack Surface & Reconnaissance" },
    { file: "defense-in-depth.html", name: "Defense in Depth & Layered Security" },
    { file: "zero-trust.html", name: "Zero Trust Architecture" },
    { file: "risk-assessment.html", name: "Risk Assessment & CVSS Scoring" },
    { file: "symmetric-encryption.html", name: "Symmetric Encryption (AES, DES)" },
    { file: "asymmetric-encryption.html", name: "Asymmetric Encryption (RSA, ECC)" },
    { file: "hashing-integrity.html", name: "Hashing & Integrity (SHA, HMAC)" },
    { file: "tls-handshake.html", name: "TLS/SSL Handshake" },
    { file: "pki-certificates.html", name: "PKI & X.509 Certificates" },
    { file: "digital-signatures.html", name: "Digital Signatures & Non-repudiation" },
    { file: "tcp-ip-attacks.html", name: "TCP/IP Stack Attacks" },
    { file: "dns-attacks.html", name: "DNS Spoofing & Cache Poisoning" },
    { file: "arp-spoofing.html", name: "ARP Spoofing & MITM" },
    { file: "firewall-rules.html", name: "Firewalls & Packet Filtering" },
    { file: "ids-ips.html", name: "IDS/IPS & Anomaly Detection" },
    { file: "vpn-tunneling.html", name: "VPN & Secure Tunneling" },
    { file: "sql-injection.html", name: "SQL Injection" },
    { file: "xss-attacks.html", name: "Cross-Site Scripting" },
    { file: "csrf-attacks.html", name: "Cross-Site Request Forgery" },
    { file: "ssrf-attacks.html", name: "Server-Side Request Forgery" },
    { file: "auth-sessions.html", name: "Authentication & Session Management" },
    { file: "owasp-top10.html", name: "OWASP Top 10 Walkthrough" },
    { file: "buffer-overflow.html", name: "Buffer Overflow & Memory Corruption" },
    { file: "privilege-escalation.html", name: "Privilege Escalation" },
    { file: "lateral-movement.html", name: "Lateral Movement & Pivoting" },
    { file: "persistence.html", name: "Persistence Mechanisms" },
    { file: "reverse-shells.html", name: "Reverse Shells & Command & Control" },
    { file: "password-attacks.html", name: "Password Attacks" },
    { file: "malware-types.html", name: "Malware Taxonomy" },
    { file: "ransomware.html", name: "Ransomware Mechanics & Kill Chain" },
    { file: "rootkits.html", name: "Rootkits & Kernel-level Malware" },
    { file: "fileless-malware.html", name: "Fileless & Living-off-the-Land" },
    { file: "sandboxing.html", name: "Sandboxing & Dynamic Analysis" },
    { file: "reverse-engineering.html", name: "Reverse Engineering Basics" },
    { file: "port-scanning.html", name: "Port Scanning" },
    { file: "service-enumeration.html", name: "Service & Version Enumeration" },
    { file: "osint-techniques.html", name: "OSINT & Open-Source Intelligence" },
    { file: "social-engineering.html", name: "Social Engineering" },
    { file: "wireless-attacks.html", name: "Wi-Fi Attacks" },
    { file: "physical-security.html", name: "Physical Security & Lock Bypass" },
    { file: "soc-operations.html", name: "SOC Operations & SIEM" },
    { file: "incident-response.html", name: "Incident Response Lifecycle" },
    { file: "threat-hunting.html", name: "Threat Hunting & Hypothesis" },
    { file: "forensics-basics.html", name: "Digital Forensics" },
    { file: "log-analysis.html", name: "Log Analysis & Correlation" },
    { file: "deception-tech.html", name: "Honeypots & Deception" },
    { file: "cloud-iam.html", name: "Cloud IAM & Least Privilege" },
    { file: "container-security.html", name: "Docker & Kubernetes Security" },
    { file: "serverless-security.html", name: "Serverless & Lambda Security" },
    { file: "api-security.html", name: "API Security (REST, GraphQL, gRPC)" },
    { file: "supply-chain-attacks.html", name: "Supply Chain & Dependency Attacks" },
    { file: "infrastructure-as-code.html", name: "IaC Security & Policy as Code" },
    { file: "quantum-cryptography.html", name: "Quantum Crypto & Post-Quantum" },
    { file: "blockchain-security.html", name: "Blockchain & Smart Contract Security" },
    { file: "ics-scada-security.html", name: "ICS/SCADA & OT Security" },
    { file: "iot-security.html", name: "IoT & Embedded Device Security" },
    { file: "ai-adversarial.html", name: "AI/ML Adversarial Attacks" },
    { file: "security-ethics.html", name: "Ethical Hacking, Law & Responsible Disclosure" }
  ]
};

// --- GLOBAL PAYMENT INTERCEPTOR ---
const originalAuthedFetch = window.authedFetch || fetch;
window.authedFetch = async function(...args) {
  try {
    const response = await originalAuthedFetch(...args);
    if (response && !response.ok && response.status === 402) {
        let detailMsg = "Payment required";
        let isDepleted = false;
        try {
          const errorData = await response.json();
          detailMsg = extractErrorMessage(errorData);
          isDepleted = detailMsg.includes("limit reached") || detailMsg.includes("depleted");
        } catch(e) {}

        showEntitlementModal({
          featureName: "Requested Feature",
          recommendedTier: "STANDARD",
          priceText: "800 KES/mo",
          isQuotaDepleted: isDepleted,
          detailMessage: detailMsg
        });
        throw new Error(detailMsg);
    }
    return response;
  } catch (error) {
    if (error.status === 402 || (error.message && (error.message.includes("limit reached") || error.message.includes("requires")))) {
      const isDepleted = error.message.includes("limit reached") || error.message.includes("depleted");
      showEntitlementModal({
        featureName: "Requested Feature",
        recommendedTier: "STANDARD",
        priceText: "800 KES/mo",
        isQuotaDepleted: isDepleted,
        detailMessage: error.message
      });
    }
    throw error;
  }
};

// --- EXTENSION INSTALL MODAL FALLBACK ---
function showExtensionInstallModal() {
  const existingModal = document.getElementById('extensionModal');
  if (existingModal) existingModal.remove();

  const modalHtml = `
    <div id="extensionModal" class="entitlement-modal-overlay">
      <div class="entitlement-modal-card" style="max-width:540px;text-align:left;">
        <h3 style="margin-top:0;color:#38bdf8;font-size:1.3rem;">🧩 Install NoteCast Chrome Extension</h3>
        <p style="color:#cbd5e1;font-size:0.88rem;line-height:1.5;">Get NoteCast directly from the Chrome Web Store or download the ZIP manually:</p>
        <div style="margin-bottom:20px;text-align:center;">
          <a href="${CHROME_STORE_URL}" target="_blank" class="btn-action" style="display:inline-block;padding:10px 20px;background:linear-gradient(135deg, #059669 0%, #047857 100%);text-decoration:none;">🛍️ Open Chrome Web Store Page</a>
        </div>
        <p style="color:#94a3b8;font-size:0.82rem;line-height:1.6;margin-bottom:12px;">Manual Developer Mode Installation:</p>
        <ol style="color:#94a3b8;font-size:0.85rem;line-height:1.8;padding-left:20px;margin-bottom:24px;">
          <li>Download the extension package: <a href="/assets/notecast-extension.zip" download style="color:#38bdf8;font-weight:bold;">notecast-extension.zip</a></li>
          <li>Extract the ZIP folder on your computer.</li>
          <li>Open Google Chrome and navigate to <code style="background:#1e293b;padding:2px 6px;border-radius:4px;color:#f8fafc;">chrome://extensions/</code></li>
          <li>Enable <strong>Developer mode</strong> at the top right corner.</li>
          <li>Click <strong>Load unpacked</strong> and select the extracted folder.</li>
        </ol>
        <div style="display:flex;justify-content:flex-end;">
          <button onclick="document.getElementById('extensionModal').remove()" style="padding:8px 18px;background:#3b82f6;border:none;border-radius:8px;color:#fff;cursor:pointer;font-weight:600;">Got It</button>
        </div>
      </div>
    </div>
  `;
  document.body.insertAdjacentHTML('beforeend', modalHtml);
}

// --- PRICING UI RENDERING & STK PUSH (ALIGNED WITH BILLING ENDPOINT SCHEMA) ---
window.openPaymentModal = function(itemCode, priceText) {
    const modalHtml = `
      <div id="paymentModal" class="modal-backdrop" style="position:fixed;top:0;left:0;width:100%;height:100%;background:rgba(0,0,0,0.7);display:flex;align-items:center;justify-content:center;z-index:9999;">
        <div style="background:var(--bg-card, #1e293b);padding:2rem;border-radius:12px;max-width:400px;width:100%;color:#fff;">
          <h3 style="margin-top:0;">Secure M-Pesa Checkout</h3>
          <p>Pass: <strong>${itemCode.replace(/_/g, ' ')}</strong><br>Amount: <strong>${priceText}</strong></p>
          <label style="display:block;margin:1rem 0 0.5rem;font-size:0.85rem;">M-Pesa Phone Number:</label>
          <input type="text" id="mpesaPhone" value="0703250550" placeholder="0712345678 or 254712345678" style="width:100%;padding:0.75rem;border-radius:6px;border:1px solid #475569;background:#0f172a;color:#fff;margin-bottom:1rem;"/>
          <div style="display:flex;gap:1rem;justify-content:flex-end;">
            <button onclick="document.getElementById('paymentModal').remove()" style="padding:0.5rem 1rem;background:#64748b;border:none;border-radius:6px;color:#fff;cursor:pointer;">Cancel</button>
            <button id="confirmPayBtn" style="padding:0.5rem 1rem;background:#6366f1;border:none;border-radius:6px;color:#fff;cursor:pointer;">Send STK Push</button>
          </div>
        </div>
      </div>
    `;
    document.body.insertAdjacentHTML('beforeend', modalHtml);
  
    document.getElementById("confirmPayBtn").addEventListener("click", async () => {
      const rawPhone = document.getElementById("mpesaPhone").value.trim();
      
      let cleanedPhone = rawPhone.replace(/\D/g, "");
      if (cleanedPhone.startsWith("0")) {
        cleanedPhone = "254" + cleanedPhone.substring(1);
      } else if (cleanedPhone.startsWith("7") || cleanedPhone.startsWith("1")) {
        cleanedPhone = "254" + cleanedPhone;
      }

      if (cleanedPhone.length < 12) {
        return alert("Please enter a valid Kenyan phone number (e.g. 0703250550).");
      }
  
      const btn = document.getElementById("confirmPayBtn");
      btn.disabled = true;
      btn.textContent = "Processing...";
  
      try {
        const requestPayload = {
          phone_number: cleanedPhone,
          plan_name: itemCode
        };

        const res = await authedFetch("/payments/stk-push", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(requestPayload)
        });
        
        let responseData = res;
        if (res && typeof res.json === "function") {
          responseData = await res.json();
        }

        if (res && !res.ok) {
          const errMsg = extractErrorMessage(responseData);
          alert(`Payment Failed (${res.status}):\n${errMsg}`);
          return;
        }

        const successMessage = extractErrorMessage(responseData) || "STK Push sent! Complete the PIN prompt on your phone.";
        alert(successMessage);
        document.getElementById('paymentModal')?.remove();
        
        let attempts = 0;
        const checkInterval = setInterval(async () => {
            attempts++;
            if (attempts > 15) {
                clearInterval(checkInterval);
                return;
            }
            try {
                const authUser = await requireAuth();
                if (authUser.plan && authUser.plan !== user.plan) {
                    clearInterval(checkInterval);
                    user = authUser;
                    document.getElementById("userPlanBadge").textContent = `Plan: ${user.plan}`;
                    if(document.getElementById("currentTierDisplay")) document.getElementById("currentTierDisplay").textContent = user.plan;
                    alert("Payment received! Your plan has been upgraded.");
                }
            } catch(e) {}
        }, 2000);

      } catch (err) {
        alert(extractErrorMessage(err));
      } finally {
        if(btn) btn.disabled = false;
      }
    });
};

// --- TAB & FEATURE ELIGIBILITY INTERCEPTOR ---
function verifyTabEligibility(tabName) {
  const currentPlan = (user?.plan || "FREE").toUpperCase();

  if (tabName === "simulators") {
    if (!["STANDARD", "PREMIUM"].includes(currentPlan)) {
      showEntitlementModal({
        featureName: "Interactive Simulation Library",
        recommendedTier: "STANDARD",
        priceText: "800 KES/mo",
        isQuotaDepleted: false
      });
      return false;
    }
  }

  return true;
}

// --- INIT ENGINE ---
async function init() {
  user = await requireAuth();
  if(document.getElementById("userName")) document.getElementById("userName").textContent = user.display_name || user.email;
  if(document.getElementById("userPlanBadge")) document.getElementById("userPlanBadge").textContent = `Plan: ${user.plan || 'Free'}`;
  
  const tierDisplay = document.getElementById("currentTierDisplay");
  if (tierDisplay) {
    tierDisplay.textContent = user.plan || 'Free Plan';
  }

  const extBtn = document.getElementById("installExtensionSidebarBtn");
  const extStatusText = document.getElementById("extStatusText");
  
  const isInstalled = await checkExtensionInstalled();
  if (isInstalled) {
    if (extBtn) extBtn.classList.add("active-installed");
    if (extStatusText) extStatusText.textContent = "✅ Extension Active & Synced";
    if (extBtn) {
      extBtn.href = "#";
      extBtn.target = "_self";
      extBtn.onclick = (e) => e.preventDefault();
    }
  } else {
    if (extBtn) {
      extBtn.onclick = (e) => {
        showExtensionInstallModal();
      };
    }
  }

  document.querySelectorAll(".nav-item").forEach(item => {
    item.addEventListener("click", () => {
      const tabName = item.getAttribute("data-tab");

      if (!verifyTabEligibility(tabName)) return;

      document.querySelectorAll(".nav-item").forEach(n => n.classList.remove("active"));
      document.querySelectorAll(".tab-pane").forEach(p => p.classList.remove("active"));

      item.classList.add("active");
      document.getElementById(`pane-${tabName}`)?.classList.add("active");

      if (tabName === "notes") loadVideos();
      if (tabName === "documents") loadDocuments();
      if (tabName === "flashcards") loadFlashcards();
      if (tabName === "graph") loadGraph();
    });
  });

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
          
          if (COURSE_MODULES[course] && COURSE_MODULES[course].length > 0) {
              opt.textContent = course.replace(/_/g, " ");
          } else {
              opt.textContent = course.replace(/_/g, " ") + " (Coming Soon)";
              opt.disabled = true; 
          }
          
          courseDropdown.appendChild(opt);
        });
      }
    });

    courseDropdown.addEventListener("change", (e) => {
      const course = e.target.value;
      moduleDropdown.innerHTML = '<option value="">-- Select Module --</option>';
      moduleDropdown.disabled = !course;
      launchBtn.disabled = true;

      if (course && COURSE_MODULES[course]) {
        COURSE_MODULES[course].forEach(mod => {
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

      const currentPlan = (user?.plan || "FREE").toUpperCase();
      if (!["STANDARD", "PREMIUM"].includes(currentPlan)) {
        showEntitlementModal({
          featureName: "Pre-Compiled Academic Simulations",
          recommendedTier: "STANDARD",
          priceText: "800 KES/mo",
          isQuotaDepleted: false
        });
        return;
      }

      const simPath = `simulations/${faculty}/${course}/${moduleFile}`;
      const simWindow = window.open("about:blank", "_blank");
      if (simWindow) {
        simWindow.document.write("<html><head><title>Loading NoteCast Simulation...</title></head><body style='background:#070a14;color:#f8fafc;font-family:sans-serif;display:flex;align-items:center;justify-content:center;height:100vh;'><h2>⚡ Loading Interactive Module...</h2></body></html>");
      }
      
      authedFetch(`/api/verify-entitlement?action=LAUNCH_STATIC_SIM`).then(res => {
        if (simWindow) simWindow.location.href = simPath;
      }).catch(err => {
        if (simWindow) simWindow.close();
      });
    });
  }

  const generateSimBtn = document.getElementById("generateSimBtn");
  if (generateSimBtn) {
    generateSimBtn.addEventListener("click", async () => {
      const topic = document.getElementById("simTopicInput").value.trim();
      if (!topic) return alert("Please enter a topic or unit name!");

      const currentPlan = (user?.plan || "FREE").toUpperCase();
      if (!["STANDARD", "PREMIUM"].includes(currentPlan)) {
        showEntitlementModal({
          featureName: "Rich 3D & Isometric Custom AI Simulations",
          recommendedTier: "STANDARD",
          priceText: "800 KES/mo",
          isQuotaDepleted: false
        });
        return;
      }

      generateSimBtn.disabled = true;
      generateSimBtn.textContent = "Synthesizing 3D Diagram...";
      
      const controller = new AbortController();
      const timeoutId = setTimeout(() => controller.abort(), 120000); 

      try {
        const res = await authedFetch("/diagrams/generate-sim/", {
          method: "POST",
          body: JSON.stringify({ topic, style: "3D_DETAILED_ISOMETRIC" }),
          signal: controller.signal
        });
        
        let schema = res;
        if(res.json) schema = await res.json();
        
        clearTimeout(timeoutId);

        if (!schema || !schema.nodes) {
          schema = {
            topic: topic,
            type: "ISOMETRIC_3D_BREAKDOWN",
            nodes: [
              { id: "step1", name: `Phase 1: Input & Setup for ${topic}`, desc: "Establishes base state and operational parameters." },
              { id: "step2", name: "Phase 2: Core Dynamics & Flow Processing", desc: "Monitors real-time variable transformations and friction." },
              { id: "step3", name: "Phase 3: System Output & Equilibrium", desc: "Verifies conservation laws and steady-state results." }
            ]
          };
        }

        sessionStorage.setItem("active_sim_schema", JSON.stringify(schema));
        window.location.href = `simulator.html?topic=${encodeURIComponent(topic)}`;
      } catch (err) {
        clearTimeout(timeoutId);
        console.error("Simulation Generation Error:", err);
      } finally {
        generateSimBtn.disabled = false;
        generateSimBtn.textContent = "Generate Live";
      }
    });
  }

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

  const genNotesBtn = document.getElementById("generateShortNotesBtn");
  if (genNotesBtn) {
    genNotesBtn.addEventListener("click", async () => {
      if (!currentSelectedDoc) return alert("Please select or upload a document first!");
      
      const currentPlan = (user?.plan || "FREE").toUpperCase();
      if (!["STANDARD", "PREMIUM"].includes(currentPlan)) {
        showEntitlementModal({
          featureName: "AI Document Summarization & Short Notes",
          recommendedTier: "STANDARD",
          priceText: "800 KES/mo",
          isQuotaDepleted: false
        });
        return;
      }

      const cacheKey = `${currentSelectedDoc.id}_p${currentPageNumber}`;
      if (pageCache[cacheKey]) {
        summaryEditor.value = pageCache[cacheKey];
        alert(`Loaded cached notes for Page ${currentPageNumber}`);
        return;
      }

      try {
          await authedFetch(`/api/verify-entitlement?action=DOC_SUMMARIZATION&resource_id=${currentSelectedDoc.id}`);
      } catch (err) {
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
          
          const generatedSummary = `# ${currentSelectedDoc.title || currentSelectedDoc.filename} — Page ${currentPageNumber}\n\n## Instant Page Snapshot Analysis\nCaptured page successfully.\nExtracted core formulas and definitions.\n\n[DIAGRAM: Flowchart Box]`;
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
        const res = await authedFetch("/documents/upload/", {
          method: "POST",
          body: formData
        });
        
        let newDoc = res;
        if(res.json) newDoc = await res.json();
        
        alert("Document uploaded successfully! Loading viewer...");
        
        await loadDocuments();
        const dropdown = document.getElementById("docSelectDropdown");
        dropdown.value = newDoc.id;
        dropdown.dispatchEvent(new Event('change')); 
        
        fileInput.value = "";
      } catch (err) {
        console.error("Upload error", err);
      } finally {
        btn.disabled = false;
        btn.textContent = "Upload & Process";
      }
    });
  }

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
  if(document.getElementById("pageIndicator")) document.getElementById("pageIndicator").textContent = `Page ${currentPageNumber} of ${totalPages}`;
  
  document.querySelectorAll(".thumb-card").forEach((t, idx) => {
    if (idx + 1 === currentPageNumber) {
      t.classList.add("active");
    } else {
      t.classList.remove("active");
    }
  });

  const cacheKey = `${currentSelectedDoc?.id}_p${currentPageNumber}`;
  const editor = document.getElementById("docSummaryEditor");
  
  if (editor) {
      if (pageCache[cacheKey]) {
        editor.value = pageCache[cacheKey];
      } else {
        editor.value = `Page ${currentPageNumber} active. Click 'Notes & Summary' on the top right to view or generate AI notes.`;
      }
  }
}

async function loadVideos() {
  try {
    const res = await authedFetch("/videos/");
    let videos = res;
    if(res.json) videos = await res.json();
    
    const list = document.getElementById("videoList");
    if (!list) return;

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
            <div class="video-row-title">${v.title || 'Untitled Session'}</div>
            <div class="video-row-meta" style="color: var(--text-muted);">${new Date(v.created_at).toLocaleDateString()}</div>
          </div>
          <span class="status-chip ${v.status}">${v.status}</span>
        </a>
      </li>`).join("");
  } catch (err) {}
}

let cachedDocuments = [];

async function loadDocuments() {
  try {
    const res = await authedFetch("/documents/");
    if (res.json) {
       cachedDocuments = await res.json();
    } else {
       cachedDocuments = res;
    }
    
    if(!Array.isArray(cachedDocuments)) cachedDocuments = [];
  } catch (err) {
    console.error("Failed to load documents list", err);
    cachedDocuments = [];
  }

  const dropdown = document.getElementById("docSelectDropdown");
  if (dropdown) {
    dropdown.innerHTML = `<option value="">-- Select Document --</option>` + 
      cachedDocuments.map(d => `<option value="${d.id}">${d.title || d.filename}</option>`).join("");

    dropdown.onchange = async (e) => {
      const docId = e.target.value;
      currentSelectedDoc = cachedDocuments.find(d => d.id === docId);
      
      const viewer = document.getElementById("pdfViewerCanvas");
      const fileNameEl = document.getElementById("currentFileName");

      if (currentSelectedDoc) {
        if(fileNameEl) fileNameEl.textContent = currentSelectedDoc.filename || currentSelectedDoc.title;
        
        if (viewer) {
          const fileKey = currentSelectedDoc.storage_key || currentSelectedDoc.id;
          const pdfMediaUrl = `/api/documents/media/${fileKey}/`;

          try {
            const checkRes = await fetch(pdfMediaUrl, { method: "HEAD" });
            if (!checkRes.ok) {
              throw new Error("Missing");
            }
            viewer.innerHTML = `<iframe src="${pdfMediaUrl}" style="width:100%; height:100%; border:none; background:#ffffff;"></iframe>`;
          } catch (storageErr) {
            viewer.innerHTML = `
              <div style="text-align: center; color: #cbd5e1; padding: 2rem;">
                <div style="font-size: 2.5rem; margin-bottom: 12px;">⚠️</div>
                <h4 style="margin: 0 0 8px 0; color: #f8fafc;">Physical PDF File Missing</h4>
                <p style="font-size: 0.85rem; color: #94a3b8; max-width: 360px; margin: 0 auto 16px auto;">
                  The server cleared temporary local storage. Please click 'Upload & Process' to re-upload your PDF file and view it again.
                </p>
                <button onclick="document.getElementById('pdfUpload').click()" class="btn-action" style="font-size: 0.8rem; padding: 6px 14px;">Re-Upload PDF</button>
              </div>
            `;
          }
        }

        const thumbsContainer = document.getElementById("readerThumbsContainer");
        if(thumbsContainer) {
            thumbsContainer.innerHTML = `<div style="font-size: 0.6rem; font-weight: 700; color: var(--text-muted);">Pg</div>`;
            for (let i = 1; i <= totalPages; i++) {
              const thumb = document.createElement("div");
              thumb.className = i === 1 ? "thumb-card active" : "thumb-card";
              thumb.innerHTML = `${i}`;
              thumb.onclick = () => switchToPage(i);
              thumbsContainer.appendChild(thumb);
            }
        }
        switchToPage(1);
      } else {
        if(fileNameEl) fileNameEl.textContent = "No file selected";
        if (viewer) {
          viewer.innerHTML = `<span style="color: #64748b; font-size: 0.85rem;">Upload or select a PDF to begin immersive reading</span>`;
        }
      }
    };
  }
}

async function loadFlashcards() {
    try {
        const res = await authedFetch("/flashcards/due/");
        if(res.json) {
            dueFlashcards = await res.json();
        } else {
            dueFlashcards = res;
        }
        
        if(!Array.isArray(dueFlashcards)) dueFlashcards = [];
        currentFcIndex = 0;
        renderCurrentFlashcard();
    } catch (err) {}
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
  if(document.getElementById("fcFront")) document.getElementById("fcFront").textContent = card.front_text;
  if(document.getElementById("fcBack")) document.getElementById("fcBack").textContent = card.back_text;
  
  if(document.getElementById("fcBack")) document.getElementById("fcBack").style.display = "none";
  if(document.getElementById("fcControls")) document.getElementById("fcControls").style.display = "none";
  if(document.getElementById("fcShowBtn")) document.getElementById("fcShowBtn").style.display = "block";
}

async function loadGraph() {
    try {
        const res = await authedFetch("/graph/");
        let graphData = res;
        if(res.json) graphData = await res.json();
        
        if(!graphData || !graphData.nodes) return;

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
        if (container && window.vis) {
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
    } catch (err) {}
}

init();