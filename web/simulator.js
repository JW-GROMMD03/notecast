const canvas = document.getElementById('simCanvas');
const ctx = canvas.getContext('2d');
const container = document.getElementById('canvasContainer');
const controlsContainer = document.getElementById('controlsContainer');
const cycleMetric = document.getElementById('cycleMetric');
const explanationText = document.getElementById('explanationText');
const voiceSelect = document.getElementById('voiceSelect');
const speakBtn = document.getElementById('speakBtn');
const stopSpeakBtn = document.getElementById('stopSpeakBtn');

let width = container.clientWidth;
let height = container.clientHeight;
canvas.width = width;
canvas.height = height;

window.addEventListener('resize', () => {
  width = container.clientWidth;
  height = container.clientHeight;
  canvas.width = width;
  canvas.height = height;
});

// 1. Load Dynamic Schema from sessionStorage (Supports ANY Subject: Biology, Astronomy, Physics, Software)
let schema = JSON.parse(sessionStorage.getItem("active_sim_schema"));

if (!schema || !schema.nodes) {
  schema = {
    title: "Dynamic Process Simulation",
    description: "An adaptive interactive simulation visualizing step-by-step workflow and component interactions.",
    nodes: [
      { id: "n1", label: "Initial State", x_pct: 20, y_pct: 50, color: "#3b82f6", shape: "pill" },
      { id: "n2", label: "Transformation Phase", x_pct: 50, y_pct: 35, color: "#f59e0b", shape: "box" },
      { id: "n3", label: "Final Outcome", x_pct: 80, y_pct: 65, color: "#10b981", shape: "circle" }
    ],
    edges: [
      { from: "n1", to: "n2", particle_color: "#a855f7", label: "Trigger / Input" },
      { from: "n2", to: "n3", particle_color: "#34d399", label: "Resultant Flow" }
    ],
    parameters: [
      { id: "p1", label: "Process Velocity", min: 1, max: 25, default: 6 },
      { id: "p2", label: "Energy / Rate", min: 1, max: 10, default: 5 }
    ]
  };
}

document.getElementById('headerTitle').textContent = schema.title;
document.getElementById('simHeading').textContent = schema.title;
document.getElementById('simDesc').textContent = schema.description;

// 2. Universal Dynamic Explanation Builder (Works for Biology, Astronomy, Software, Economics, etc.)
function buildDynamicExplanation(s) {
  let html = `<strong>Topic Analysis: ${s.title}</strong><br><br>`;
  html += `<em>${s.description}</em><br><br>`;
  html += `<strong>Sequential Process Stages:</strong><br>`;
  
  if (s.nodes && s.nodes.length > 0) {
    s.nodes.forEach((n, idx) => {
      let stageRole = "Acts as a critical transition or processing stage within the cycle.";
      const lbl = n.label.toLowerCase();
      
      // Automatic semantic detection across different academic disciplines
      if (idx === 0) stageRole = "Initial entry point, source input, or starting stimulus.";
      else if (idx === s.nodes.length - 1) stageRole = "Terminal destination, output product, or final state.";
      else if (lbl.includes("stomach") || lbl.includes("organ") || lbl.includes("cell")) stageRole = "Biological processing unit responsible for chemical or physical decomposition.";
      else if (lbl.includes("sun") || lbl.includes("star") || lbl.includes("core")) stageRole = "Central gravitational or energetic anchor radiating mass/force.";
      else if (lbl.includes("planet") || lbl.includes("orbit")) stageRole = "Revolving body maintaining trajectory via centripetal balance.";
      else if (lbl.includes("gateway") || lbl.includes("router")) stageRole = "Routing hub directing communication pathways.";

      html += `• <strong>Stage ${idx + 1}: ${n.label}</strong> — ${stageRole}<br>`;
    });
  }

  html += `<br><strong>Interactive Dynamics:</strong><br>`;
  html += `Moving particles represent active transfer of energy, data, matter, or signals along connectors. Use the sliders on the right to manipulate velocity and load parameters in real time.`;
  return html;
}

explanationText.innerHTML = buildDynamicExplanation(schema);

// 3. Web Speech API Voice Narrator Setup
let voices = [];
function populateVoices() {
  if (!window.speechSynthesis) return;
  voices = window.speechSynthesis.getVoices();
  voiceSelect.innerHTML = "";
  voices.forEach((v, index) => {
    const option = document.createElement('option');
    option.value = index;
    option.textContent = `${v.name} (${v.lang})`;
    if (v.default || v.lang.includes('en')) option.selected = true;
    voiceSelect.appendChild(option);
  });
}
if (window.speechSynthesis) {
  populateVoices();
  window.speechSynthesis.onvoiceschanged = populateVoices;
}

speakBtn.addEventListener('click', () => {
  if (!window.speechSynthesis) return alert("Text-to-speech not supported in this browser.");
  window.speechSynthesis.cancel();
  const utterance = new SpeechSynthesisUtterance(explanationText.innerText);
  const selectedVoiceIndex = voiceSelect.value;
  if (voices[selectedVoiceIndex]) utterance.voice = voices[selectedVoiceIndex];
  utterance.rate = 1.0;
  window.speechSynthesis.speak(utterance);
});

stopSpeakBtn.addEventListener('click', () => {
  if (window.speechSynthesis) window.speechSynthesis.cancel();
});

// 4. Generate Dynamic Sliders from AI Schema
const runtimeParams = {};
if (schema.parameters && schema.parameters.length > 0) {
  schema.parameters.forEach(param => {
    runtimeParams[param.id] = param.default;
    const group = document.createElement('div');
    group.className = 'control-group';
    const label = document.createElement('label');
    label.innerHTML = `${param.label} <span id="val_${param.id}" style="color: #fff;">${param.default}</span>`;
    const slider = document.createElement('input');
    slider.type = 'range';
    slider.min = param.min;
    slider.max = param.max;
    slider.value = param.default;
    slider.addEventListener('input', (e) => {
      const val = parseInt(e.target.value);
      runtimeParams[param.id] = val;
      document.getElementById(`val_${param.id}`).textContent = val;
    });
    group.appendChild(label);
    group.appendChild(slider);
    controlsContainer.appendChild(group);
  });
}

// 5. Helper Function for Rounded Rectangles
function roundRect(ctx, x, y, width, height, radius, fill, stroke) {
  ctx.beginPath();
  ctx.moveTo(x + radius, y);
  ctx.lineTo(x + width - radius, y);
  ctx.quadraticCurveTo(x + width, y, x + width, y + radius);
  ctx.lineTo(x + width, y + height - radius);
  ctx.quadraticCurveTo(x + width, y + height, x + width - radius, y + height);
  ctx.lineTo(x + radius, y + height);
  ctx.quadraticCurveTo(x, y + height, x, y + height - radius);
  ctx.lineTo(x, y + radius);
  ctx.quadraticCurveTo(x, y, x + radius, y);
  ctx.closePath();
  if (fill) ctx.fill();
  if (stroke) ctx.stroke();
}

// 6. Universal Domain-Agnostic Shape Renderer
function drawNode(ctx, n, width, height) {
  const x = (n.x_pct / 100) * width;
  const y = (n.y_pct / 100) * height;
  const w = 120;
  const h = 56;

  ctx.save();
  ctx.shadowBlur = 20;
  ctx.shadowColor = n.color || '#3b82f6';

  const shape = (n.shape || '').toLowerCase();
  const labelLower = n.label.toLowerCase();

  if (shape.includes('sphere') || shape.includes('orbit') || labelLower.includes('sun') || labelLower.includes('planet') || labelLower.includes('moon')) {
    // Astronomical Spherical Body
    const radius = 28;
    const gradient = ctx.createRadialGradient(x - 8, y - 8, 4, x, y, radius);
    gradient.addColorStop(0, '#ffffff');
    gradient.addColorStop(0.3, n.color || '#f59e0b');
    gradient.addColorStop(1, '#070a14');
    
    ctx.fillStyle = gradient;
    ctx.beginPath();
    ctx.arc(x, y, radius, 0, Math.PI * 2);
    ctx.fill();

    ctx.strokeStyle = n.color || '#f59e0b';
    ctx.lineWidth = 2;
    ctx.stroke();
  } else if (shape.includes('cylinder') || shape.includes('db') || labelLower.includes('database') || labelLower.includes('storage')) {
    // Database / Cylindrical Container
    ctx.fillStyle = n.color || '#10b981';
    ctx.beginPath();
    ctx.ellipse(x, y - 18, w/2, 14, 0, 0, Math.PI * 2);
    ctx.fill();
    ctx.fillRect(x - w/2, y - 18, w, 36);
    ctx.beginPath();
    ctx.ellipse(x, y + 18, w/2, 14, 0, 0, Math.PI * 2);
    ctx.fill();
  } else if (shape.includes('pill') || shape.includes('organ') || labelLower.includes('stomach') || labelLower.includes('cell') || labelLower.includes('mouth')) {
    // Organic Pill / Biological Node Shape
    ctx.fillStyle = '#0f172a';
    ctx.strokeStyle = n.color || '#ec4899';
    ctx.lineWidth = 3;
    roundRect(ctx, x - w/2, y - h/2, w, h, 28, true, true);
  } else {
    // Modern Rounded Rectangle Box (Default for generic steps, courses, and systems)
    ctx.fillStyle = '#0f172a';
    ctx.strokeStyle = n.color || '#3b82f6';
    ctx.lineWidth = 2.5;
    roundRect(ctx, x - w/2, y - h/2, w, h, 14, true, true);
  }

  ctx.restore();

  // Typography / Label
  ctx.fillStyle = 'white';
  ctx.font = 'bold 12px -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif';
  ctx.textAlign = 'center';
  ctx.textBaseline = 'middle';
  ctx.fillText(n.label, x, y);
}

// 7. Physics Engine & Animation Loop
let particles = [];
let cycles = 0;
let lastSpawnTime = 0;

function animate(timestamp) {
  ctx.clearRect(0, 0, width, height);

  const paramKeys = Object.keys(runtimeParams);
  const spawnRateMod = paramKeys.length > 0 ? runtimeParams[paramKeys[0]] : 5; 
  const speedMod = paramKeys.length > 1 ? runtimeParams[paramKeys[1]] : 5;

  // Draw Connectors / Edges
  if (schema.edges) {
    schema.edges.forEach(e => {
      const fromNode = schema.nodes.find(n => n.id === e.from);
      const toNode = schema.nodes.find(n => n.id === e.to);
      if (fromNode && toNode) {
        const x1 = (fromNode.x_pct / 100) * width;
        const y1 = (fromNode.y_pct / 100) * height;
        const x2 = (toNode.x_pct / 100) * width;
        const y2 = (toNode.y_pct / 100) * height;

        ctx.beginPath();
        ctx.moveTo(x1, y1);
        ctx.lineTo(x2, y2);
        ctx.strokeStyle = '#1e293b';
        ctx.lineWidth = 3.5;
        ctx.stroke();

        if (e.label) {
          ctx.fillStyle = '#94a3b8';
          ctx.font = '11px -apple-system, sans-serif';
          ctx.textAlign = 'center';
          ctx.fillText(e.label, (x1 + x2) / 2, ((y1 + y2) / 2) - 10);
        }
      }
    });
  }

  // Draw Dynamic Nodes
  if (schema.nodes) {
    schema.nodes.forEach(n => drawNode(ctx, n, width, height));
  }

  // Particle Spawner
  const spawnInterval = Math.max(100, 2000 - (spawnRateMod * 60)); 
  if (timestamp - lastSpawnTime > spawnInterval && schema.edges) {
    const edge = schema.edges[Math.floor(Math.random() * schema.edges.length)];
    const fromNode = schema.nodes.find(n => n.id === edge.from);
    const toNode = schema.nodes.find(n => n.id === edge.to);

    if (fromNode && toNode) {
      particles.push({
        x: (fromNode.x_pct / 100) * width,
        y: (fromNode.y_pct / 100) * height,
        targetX: (toNode.x_pct / 100) * width,
        targetY: (toNode.y_pct / 100) * height,
        color: edge.particle_color || '#3b82f6',
        speed: (2 + Math.random() * 2) * (speedMod / 5)
      });
    }
    lastSpawnTime = timestamp;
  }

  // Update and Draw Data/Matter Flow Particles
  for (let i = particles.length - 1; i >= 0; i--) {
    let p = particles[i];
    let dx = p.targetX - p.x;
    let dy = p.targetY - p.y;
    let dist = Math.sqrt(dx * dx + dy * dy);

    if (dist < p.speed) {
      cycles++;
      cycleMetric.textContent = cycles;
      particles.splice(i, 1);
    } else {
      p.x += (dx / dist) * p.speed;
      p.y += (dy / dist) * p.speed;
      ctx.beginPath();
      ctx.arc(p.x, p.y, 6, 0, Math.PI * 2);
      ctx.fillStyle = p.color;
      ctx.shadowBlur = 14;
      ctx.shadowColor = p.color;
      ctx.fill();
      ctx.shadowBlur = 0;
    }
  }

  requestAnimationFrame(animate);
}

requestAnimationFrame(animate);