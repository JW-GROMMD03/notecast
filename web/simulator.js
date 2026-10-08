const canvas = document.getElementById('simCanvas');
const ctx = canvas.getContext('2d');
const container = document.getElementById('canvasContainer');
const controlsContainer = document.getElementById('controlsContainer');
const cycleMetric = document.getElementById('cycleMetric');

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

// 1. Load Dynamic Schema from the AI (via Dashboard)
let schema = JSON.parse(sessionStorage.getItem("active_sim_schema"));

// Fallback in case a user accesses the URL directly without generating first
if (!schema || !schema.nodes) {
  schema = {
    title: "System Flow Simulation",
    description: "A generic interactive workflow visualizing data passing through a system.",
    nodes: [
      { id: "n1", label: "Source", x_pct: 15, y_pct: 50, color: "#3b82f6" },
      { id: "n2", label: "Processor", x_pct: 50, y_pct: 50, color: "#f59e0b" },
      { id: "n3", label: "Output", x_pct: 85, y_pct: 50, color: "#10b981" }
    ],
    edges: [
      { from: "n1", to: "n2", particle_color: "#a855f7", label: "Flow A" },
      { from: "n2", to: "n3", particle_color: "#34d399", label: "Flow B" }
    ],
    parameters: [
      { id: "p1", label: "Input Rate", min: 1, max: 30, default: 5 },
      { id: "p2", label: "Processing Speed", min: 1, max: 10, default: 5 }
    ]
  };
}

// 2. Populate UI Text
document.getElementById('headerTitle').textContent = schema.title;
document.getElementById('simHeading').textContent = schema.title;
document.getElementById('simDesc').textContent = schema.description;

// 3. Generate Dynamic Controls (Sliders)
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

// 4. Physics Engine & Animation Loop
let particles = [];
let cycles = 0;
let lastSpawnTime = 0;

function animate(timestamp) {
  ctx.clearRect(0, 0, width, height);

  // Determine global modifiers based on the AI's generated parameters.
  // We map the first parameter to Spawn Rate, and the second to Particle Speed.
  const paramKeys = Object.keys(runtimeParams);
  const spawnRateMod = paramKeys.length > 0 ? runtimeParams[paramKeys[0]] : 5; 
  const speedMod = paramKeys.length > 1 ? runtimeParams[paramKeys[1]] : 5;

  // Draw Edges (Connectors)
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
        ctx.lineWidth = 3;
        ctx.stroke();

        // Optional Edge Label
        if (e.label) {
          ctx.fillStyle = '#64748b';
          ctx.font = '10px sans-serif';
          ctx.fillText(e.label, (x1 + x2) / 2, ((y1 + y2) / 2) - 8);
        }
      }
    });
  }

  // Draw Nodes
  if (schema.nodes) {
    schema.nodes.forEach(n => {
      const x = (n.x_pct / 100) * width;
      const y = (n.y_pct / 100) * height;

      // Glow effect
      ctx.shadowBlur = 15;
      ctx.shadowColor = n.color || '#3b82f6';
      
      ctx.fillStyle = n.color || '#3b82f6';
      ctx.beginPath();
      ctx.arc(x, y, 25, 0, Math.PI * 2);
      ctx.fill();

      // Reset shadow for text
      ctx.shadowBlur = 0;

      ctx.fillStyle = 'white';
      ctx.font = 'bold 12px sans-serif';
      ctx.textAlign = 'center';
      ctx.fillText(n.label, x, y - 35);
    });
  }

  // Particle Spawner
  // Higher spawnRateMod = faster spawn interval
  const spawnInterval = Math.max(100, 2000 - (spawnRateMod * 60)); 
  if (timestamp - lastSpawnTime > spawnInterval && schema.edges) {
    // Pick a random edge to spawn a flow particle
    const edge = schema.edges[Math.floor(Math.random() * schema.edges.length)];
    const fromNode = schema.nodes.find(n => n.id === edge.from);
    const toNode = schema.nodes.find(n => n.id === edge.to);

    if (fromNode && toNode) {
      particles.push({
        x: (fromNode.x_pct / 100) * width,
        y: (fromNode.y_pct / 100) * height,
        targetX: (toNode.x_pct / 100) * width,
        targetY: (toNode.y_pct / 100) * height,
        color: edge.particle_color || '#ffffff',
        speed: (2 + Math.random() * 2) * (speedMod / 5) // Scale speed via slider
      });
    }
    lastSpawnTime = timestamp;
  }

  // Update and Draw Particles
  for (let i = particles.length - 1; i >= 0; i--) {
    let p = particles[i];
    let dx = p.targetX - p.x;
    let dy = p.targetY - p.y;
    let dist = Math.sqrt(dx * dx + dy * dy);

    if (dist < p.speed) {
      // Particle reached destination node
      cycles++;
      cycleMetric.textContent = cycles;
      particles.splice(i, 1);
    } else {
      p.x += (dx / dist) * p.speed;
      p.y += (dy / dist) * p.speed;

      ctx.beginPath();
      ctx.arc(p.x, p.y, 5, 0, Math.PI * 2);
      ctx.fillStyle = p.color;
      ctx.shadowBlur = 10;
      ctx.shadowColor = p.color;
      ctx.fill();
      ctx.shadowBlur = 0;
    }
  }

  requestAnimationFrame(animate);
}

// Start simulation
requestAnimationFrame(animate);