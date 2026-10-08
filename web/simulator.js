// ============================================================================
// AI 3D KNOWLEDGE SIMULATOR ENGINE (THREE.JS)
// Domain-Agnostic: Renders Biology, Physics, Tech, and Chemistry in True 3D
// ============================================================================

const canvas = document.getElementById('simCanvas');
const container = document.getElementById('canvasContainer');
const labelsContainer = document.getElementById('labelsContainer');
const controlsContainer = document.getElementById('controlsContainer');
const cycleMetric = document.getElementById('cycleMetric');
const explanationText = document.getElementById('explanationText');
const voiceSelect = document.getElementById('voiceSelect');
const speakBtn = document.getElementById('speakBtn');
const stopSpeakBtn = document.getElementById('stopSpeakBtn');

let width = container.clientWidth;
let height = container.clientHeight;

// ============================================================================
// 1. DATA SCHEMA INGESTION & FALLBACK
// ============================================================================
let schema = null;
try {
  schema = JSON.parse(sessionStorage.getItem("active_sim_schema"));
} catch (e) {
  console.warn("No active schema found in session storage. Loading default 3D environment.");
}

// Highly detailed fallback schema if the user directly navigates to the page
if (!schema || !schema.nodes) {
  schema = {
    title: "Human Digestive Process (3D)",
    description: "Biomechanical and chemical breakdown of macromolecules into absorbable nutrients.",
    nodes: [
      { id: "n1", label: "Oral Cavity", x: -4, y: 3, z: 0, color: "#fca5a5", shape_3d: "sphere" },
      { id: "n2", label: "Stomach", x: 0, y: 0, z: 1, color: "#ef4444", shape_3d: "organic" },
      { id: "n3", label: "Small Intestine", x: 3, y: -3, z: -1, color: "#10b981", shape_3d: "tube" },
      { id: "n4", label: "Liver & Pancreas", x: 1.5, y: 1.5, z: -2, color: "#8b5cf6", shape_3d: "organic" }
    ],
    edges: [
      { from: "n1", to: "n2", particle_color: "#ffffff", label: "Bolus Transmit (Esophagus)" },
      { from: "n4", to: "n2", particle_color: "#3b82f6", label: "Bile & Enzyme Secretion" },
      { from: "n2", to: "n3", particle_color: "#fde047", label: "Chyme Release" }
    ],
    parameters: [
      { id: "food_type", label: "Macronutrient Intake", type: "select", options: ["Carbohydrates", "Proteins", "Fats", "Mixed Diet"], default: "Carbohydrates" },
      { id: "enzymes", label: "Enzyme Secretion Rate", type: "slider", min: 1, max: 10, default: 5 },
      { id: "time_lapse", label: "Simulation Time Lapse", type: "slider", min: 1, max: 20, default: 4 }
    ],
    detailed_lecture: "<strong>Degree-Level Analysis: Human Digestion</strong><br><br>Digestion begins in the oral cavity where mechanical mastication and salivary amylase initiate the breakdown of starches. As the bolus descends via esophageal peristalsis, it enters the highly acidic gastric environment (pH ~1.5 - 3.5).<br><br>Here, parietal cells secrete HCl, activating pepsinogen into pepsin to cleave peptide bonds in proteins. The resulting semi-fluid 'chyme' is metered through the pyloric sphincter into the duodenum. Pancreatic lipases, proteases, and biliary emulsifiers further degrade macromolecules into monomers (glucose, amino acids, fatty acids) which are absorbed across the villi-lined epithelial border into the hepatic portal circulation. The entire system operates under strict autonomic and hormonal regulation."
  };
}

// Populate UI Headers
document.getElementById('headerTitle').textContent = schema.title;
document.getElementById('simHeading').textContent = "Conditions & Factors";
document.getElementById('simDesc').textContent = schema.description;
explanationText.innerHTML = schema.detailed_lecture || "Detailed lecture notes generating...";

// ============================================================================
// 2. TEXT-TO-SPEECH (WEB SPEECH API) ENGINE
// ============================================================================
let voices = [];
function populateVoices() {
  if (!window.speechSynthesis) return;
  voices = window.speechSynthesis.getVoices();
  voiceSelect.innerHTML = "";
  voices.forEach((v, index) => {
    const option = document.createElement('option');
    option.value = index;
    option.textContent = `${v.name} (${v.lang})`;
    // Prioritize high-quality English voices
    if (v.default || v.lang === 'en-GB' || v.lang === 'en-US') option.selected = true;
    voiceSelect.appendChild(option);
  });
}

if (window.speechSynthesis) {
  populateVoices();
  window.speechSynthesis.onvoiceschanged = populateVoices;
}

speakBtn.addEventListener('click', () => {
  if (!window.speechSynthesis) {
    alert("Text-to-speech is not supported in this browser.");
    return;
  }
  window.speechSynthesis.cancel(); // Stop current speech
  
  // Clean HTML tags to prevent the narrator from reading "strong" or "br"
  const rawText = explanationText.innerHTML;
  const cleanText = rawText.replace(/<[^>]*>?/gm, ''); 
  
  const utterance = new SpeechSynthesisUtterance(cleanText);
  const selectedVoiceIndex = voiceSelect.value;
  if (voices[selectedVoiceIndex]) {
    utterance.voice = voices[selectedVoiceIndex];
  }
  
  utterance.rate = 0.95; // Slightly slower for academic comprehension
  utterance.pitch = 1.0;
  window.speechSynthesis.speak(utterance);
});

stopSpeakBtn.addEventListener('click', () => {
  if (window.speechSynthesis) window.speechSynthesis.cancel();
});

// ============================================================================
// 3. DYNAMIC UNLIMITED CONDITIONS & PARAMETERS UI
// ============================================================================
const runtimeParams = {};

if (schema.parameters && schema.parameters.length > 0) {
  schema.parameters.forEach(param => {
    runtimeParams[param.id] = param.default;
    const group = document.createElement('div');
    group.className = 'control-group';
    
    if (param.type === "select") {
      // Generate Dropdown Selectors
      const label = document.createElement('label');
      label.innerHTML = `${param.label}`;
      const select = document.createElement('select');
      
      param.options.forEach(opt => {
        const optionEl = document.createElement('option');
        optionEl.value = opt;
        optionEl.textContent = opt;
        if (opt === param.default) optionEl.selected = true;
        select.appendChild(optionEl);
      });
      
      select.addEventListener('change', (e) => {
        runtimeParams[param.id] = e.target.value;
        console.log(`Condition updated: ${param.id} = ${e.target.value}`);
      });
      
      group.appendChild(label);
      group.appendChild(select);
    } else {
      // Generate Range Sliders
      const label = document.createElement('label');
      label.innerHTML = `${param.label} <span id="val_${param.id}" style="color: #fff;">${param.default}</span>`;
      const slider = document.createElement('input');
      slider.type = 'range';
      slider.min = param.min || 1;
      slider.max = param.max || 10;
      slider.value = param.default;
      
      slider.addEventListener('input', (e) => {
        const val = parseFloat(e.target.value);
        runtimeParams[param.id] = val;
        document.getElementById(`val_${param.id}`).textContent = val;
      });
      
      group.appendChild(label);
      group.appendChild(slider);
    }
    controlsContainer.appendChild(group);
  });
}

// ============================================================================
// 4. THREE.JS 3D SCENE & ENGINE SETUP
// ============================================================================
const scene = new THREE.Scene();
scene.background = new THREE.Color('#030712'); // Deep space dark background

const camera = new THREE.PerspectiveCamera(55, width / height, 0.1, 1000);
camera.position.set(0, 0, 14);

const renderer = new THREE.WebGLRenderer({ canvas: canvas, antialias: true, alpha: false });
renderer.setSize(width, height);
renderer.setPixelRatio(window.devicePixelRatio);
renderer.shadowMap.enabled = true;

// 3D Lighting Setup (Ambient + Directional for realistic shading)
const ambientLight = new THREE.AmbientLight(0xffffff, 0.5);
scene.add(ambientLight);

const directionalLight = new THREE.DirectionalLight(0xffffff, 1.2);
directionalLight.position.set(10, 20, 15);
scene.add(directionalLight);

const backLight = new THREE.PointLight(0x3b82f6, 1, 50);
backLight.position.set(-10, -10, -10);
scene.add(backLight);

// Orbit Controls (360-degree rotation, zoom, and pan)
const controls = new THREE.OrbitControls(camera, renderer.domElement);
controls.enableDamping = true;
controls.dampingFactor = 0.05;
controls.minDistance = 2;
controls.maxDistance = 50;

window.addEventListener('resize', () => {
  width = container.clientWidth;
  height = container.clientHeight;
  camera.aspect = width / height;
  camera.updateProjectionMatrix();
  renderer.setSize(width, height);
});

// ============================================================================
// 5. DOMAIN-AGNOSTIC 3D SHAPE BUILDER (Organic, Technical, Astronomical)
// ============================================================================
const nodeObjects = {};
const labels = [];
const nodeMeshesArray = []; // Used for Raycasting (clicking)

schema.nodes.forEach(n => {
  let geometry;
  const shape = (n.shape_3d || 'sphere').toLowerCase();
  
  if (shape === 'organic' || shape === 'stomach') {
    // Math distortion for a biological stomach/liver blob
    geometry = new THREE.SphereGeometry(1.3, 32, 32);
    const positions = geometry.attributes.position;
    for (let i = 0; i < positions.count; i++) {
      let y = positions.getY(i);
      let x = positions.getX(i);
      let z = positions.getZ(i);
      positions.setX(i, x * (1 + y * 0.2)); 
      positions.setY(i, y * 1.1);         
      positions.setZ(i, z * 0.9);         
    }
    geometry.computeVertexNormals();
  } else if (shape === 'tube' || shape === 'intestine') {
    // Torus for intestines or pipelines
    geometry = new THREE.TorusGeometry(1.2, 0.45, 16, 64, Math.PI * 1.5);
  } else if (shape === 'cube' || shape === 'server') {
    // Geometric cube for databases, software architectures, or tech nodes
    geometry = new THREE.BoxGeometry(1.8, 1.8, 1.8);
  } else {
    // Standard Sphere for Planets, Cells, Atoms
    geometry = new THREE.SphereGeometry(1.2, 64, 64);
  }

  const material = new THREE.MeshStandardMaterial({ 
    color: n.color || '#3b82f6', 
    roughness: 0.2,
    metalness: 0.3,
    transparent: true,
    opacity: 0.95
  });
  
  const mesh = new THREE.Mesh(geometry, material);
  mesh.position.set(n.x || (Math.random()*8-4), n.y || (Math.random()*8-4), n.z || (Math.random()*4-2));
  
  // Attach metadata for raycasting
  mesh.userData = { id: n.id, label: n.label, color: n.color };
  
  scene.add(mesh);
  nodeObjects[n.id] = mesh;
  nodeMeshesArray.push(mesh);

  // HTML Overlay Label Tracking
  const label = document.createElement('div');
  label.className = 'node-label';
  label.textContent = n.label;
  labelsContainer.appendChild(label);
  labels.push({ element: label, mesh: mesh });
});

// ============================================================================
// 6. 3D BEZIER CURVES FOR EDGES & CONNECTORS
// ============================================================================
const curves = [];
schema.edges.forEach(e => {
  const fromMesh = nodeObjects[e.from];
  const toMesh = nodeObjects[e.to];
  
  if (fromMesh && toMesh) {
    const start = fromMesh.position;
    const end = toMesh.position;
    
    // Create an arcing mid-point for the Bezier curve
    const midPoint = new THREE.Vector3().addVectors(start, end).multiplyScalar(0.5);
    midPoint.y += 1.5; 
    midPoint.z += 1.5;

    const curve = new THREE.QuadraticBezierCurve3(start, midPoint, end);
    curves.push({ curve: curve, edge: e });

    // Draw the visible connector line
    const points = curve.getPoints(50);
    const lineGeo = new THREE.BufferGeometry().setFromPoints(points);
    const lineMat = new THREE.LineBasicMaterial({ color: 0x334155, linewidth: 2, transparent: true, opacity: 0.5 });
    const splineObject = new THREE.Line(lineGeo, lineMat);
    scene.add(splineObject);
  }
});

// ============================================================================
// 7. RAYCASTER (CLICK INTERACTION ON 3D OBJECTS)
// ============================================================================
const raycaster = new THREE.Raycaster();
const mouse = new THREE.Vector2();

container.addEventListener('click', (event) => {
  const rect = container.getBoundingClientRect();
  mouse.x = ((event.clientX - rect.left) / width) * 2 - 1;
  mouse.y = -((event.clientY - rect.top) / height) * 2 + 1;

  raycaster.setFromCamera(mouse, camera);
  const intersects = raycaster.intersectObjects(nodeMeshesArray);

  if (intersects.length > 0) {
    const clickedMesh = intersects[0].object;
    // Visually bump the clicked node
    clickedMesh.scale.set(1.2, 1.2, 1.2);
    setTimeout(() => { clickedMesh.scale.set(1, 1, 1); }, 200);
    
    console.log(`User clicked 3D Node: ${clickedMesh.userData.label}`);
  }
});

// ============================================================================
// 8. 3D PARTICLE ANIMATION & RENDERING LOOP
// ============================================================================
let particles = [];
let cycles = 0;
let lastSpawnTime = 0;

function animate(time) {
  requestAnimationFrame(animate);
  controls.update();

  // Dynamic Parameter Extraction
  // Find a slider that might represent speed/time (default to 5)
  let speedMod = 5;
  for (const key in runtimeParams) {
    if (typeof runtimeParams[key] === 'number') {
      speedMod = runtimeParams[key];
      break; 
    }
  }
  
  // Dynamic Particle Spawning based on user-controlled speed
  const spawnRate = Math.max(100, 1500 - (speedMod * 120));
  
  if (time - lastSpawnTime > spawnRate && curves.length > 0) {
    // Pick a random edge to send data/matter through
    const randomCurveObj = curves[Math.floor(Math.random() * curves.length)];
    
    // Create glowing 3D particle sphere
    const pGeo = new THREE.SphereGeometry(0.18, 12, 12);
    const pMat = new THREE.MeshBasicMaterial({ color: randomCurveObj.edge.particle_color || '#ffffff' });
    const pMesh = new THREE.Mesh(pGeo, pMat);
    scene.add(pMesh);
    
    particles.push({
      mesh: pMesh,
      curve: randomCurveObj.curve,
      progress: 0,
      speed: 0.003 + (speedMod * 0.001) // Particle velocity tied to slider
    });
    lastSpawnTime = time;
  }

  // Animate Particles along the 3D Bezier Curves
  for (let i = particles.length - 1; i >= 0; i--) {
    let p = particles[i];
    p.progress += p.speed;
    
    if (p.progress >= 1) {
      // Particle reached destination
      scene.remove(p.mesh);
      particles.splice(i, 1);
      cycles++;
      cycleMetric.textContent = cycles;
    } else {
      // Update physical position in 3D space
      const point = p.curve.getPointAt(p.progress);
      p.mesh.position.copy(point);
    }
  }

  // Update 2D HTML Label Positions to match 3D Camera Projection
  labels.forEach(l => {
    const vector = l.mesh.position.clone();
    vector.project(camera);
    
    const x = (vector.x * 0.5 + 0.5) * width;
    const y = (vector.y * -0.5 + 0.5) * height;
    
    // Only display label if node is in front of the camera (z < 1)
    if (vector.z < 1) { 
      l.element.style.opacity = 1;
      l.element.style.left = `${x}px`;
      l.element.style.top = `${y - 45}px`; 
    } else {
      l.element.style.opacity = 0;
    }
  });

  // Render Frame
  renderer.render(scene, camera);
}

// Boot the simulation
animate(0);