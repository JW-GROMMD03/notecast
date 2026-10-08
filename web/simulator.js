// ============================================================================
// NOTECAST AI 3D KNOWLEDGE SIMULATOR ENGINE (THREE.JS - PRODUCTION GRADE)
// Domain-Agnostic: Renders Biology, Physics, Tech, Anatomy, and Chemistry in True 3D
// ============================================================================

"use strict";

const CONFIG = {
  clearColor: 0x030712,
  cameraFov: 55,
  nearClip: 0.1,
  farClip: 1000,
  dampingFactor: 0.05,
  particleBaseSpeed: 0.003
};

// DOM Element References
const DOM = {
  canvas: document.getElementById('simCanvas'),
  container: document.getElementById('canvasContainer'),
  labelsContainer: document.getElementById('labelsContainer'),
  controlsContainer: document.getElementById('controlsContainer'),
  cycleMetric: document.getElementById('cycleMetric'),
  explanationText: document.getElementById('explanationText'),
  voiceSelect: document.getElementById('voiceSelect'),
  speakBtn: document.getElementById('speakBtn'),
  stopSpeakBtn: document.getElementById('stopSpeakBtn'),
  headerTitle: document.getElementById('headerTitle'),
  simHeading: document.getElementById('simHeading'),
  simDesc: document.getElementById('simDesc')
};

let width = DOM.container.clientWidth;
let height = DOM.container.clientHeight;

// ============================================================================
// 1. DATA SCHEMA INGESTION & ROBUST ACADEMIC FALLBACK
// ============================================================================
let schema = null;
try {
  const storedSchema = sessionStorage.getItem("active_sim_schema");
  if (storedSchema) {
    schema = JSON.parse(storedSchema);
    console.info("📥 Successfully ingested dynamic simulation schema from session storage.");
  }
} catch (err) {
  console.warn("⚠️ Failed to parse active_sim_schema from sessionStorage. Falling back to default environment.", err);
}

// Comprehensive default fallback schema if accessed directly
if (!schema || !schema.nodes) {
  schema = {
    title: "Human Digestive Process (Advanced 3D)",
    description: "Biomechanical and chemical breakdown of macromolecules into absorbable nutrients across the gastrointestinal tract.",
    nodes: [
      { id: "n1", label: "Oral Cavity & Mastication", x: -4, y: 3, z: 0, color: "#fca5a5", shape_3d: "sphere", description: "Mechanical breakdown via teeth and enzymatic initiation via salivary alpha-amylase." },
      { id: "n2", label: "Gastric Environment", x: 0, y: 0, z: 1, color: "#ef4444", shape_3d: "organic", description: "Acidic protein denaturation (pH 1.5-3.5) and pepsinogen activation." },
      { id: "n3", label: "Small Intestine (Duodenum)", x: 3, y: -3, z: -1, color: "#10b981", shape_3d: "tube", description: "Enzymatic hydrolysis and absorption of monosaccharides, amino acids, and fatty acids." },
      { id: "n4", label: "Hepatic & Pancreatic Axis", x: 1.5, y: 1.5, z: -2, color: "#8b5cf6", shape_3d: "organic", description: "Bile emulsification and bicarbonate/lipase secretion." }
    ],
    edges: [
      { from: "n1", to: "n2", particle_color: "#ffffff", label: "Esophageal Peristalsis" },
      { from: "n4", to: "n2", particle_color: "#3b82f6", label: "Bile & Enzyme Secretion" },
      { from: "n2", to: "n3", particle_color: "#fde047", label: "Chyme Metering" }
    ],
    parameters: [
      { id: "food_type", label: "Macronutrient Profile", type: "select", options: ["Carbohydrates", "Proteins", "Fats", "Mixed Balanced Diet"], default: "Carbohydrates" },
      { id: "enzymes", label: "Enzyme Secretion Rate", type: "slider", min: 1, max: 10, default: 5 },
      { id: "time_lapse", label: "Simulation Velocity", type: "slider", min: 1, max: 20, default: 6 }
    ],
    detailed_lecture: "<strong>Degree-Level Analysis: Human Digestion & Metabolism</strong><br><br>Digestion begins in the oral cavity where mechanical mastication and salivary amylase initiate the breakdown of complex starches. As the bolus descends via synchronized esophageal peristalsis, it enters the highly acidic gastric environment.<br><br>Here, parietal cells secrete hydrochloric acid, activating pepsinogen into active pepsin to cleave peptide bonds in proteins. The resulting semi-fluid chyme is metered through the pyloric sphincter into the duodenum. Pancreatic lipases, proteases, and biliary emulsifiers further degrade macromolecules into monomers (glucose, amino acids, fatty acids) which are absorbed across the villi-lined epithelial border into the hepatic portal circulation. The entire metabolic cascade operates under strict autonomic and hormonal feedback."
  };
}

// Initialize UI Metadata Headers
DOM.headerTitle.textContent = schema.title;
DOM.simHeading.textContent = "Conditions & Factors";
DOM.simDesc.textContent = schema.description;
DOM.explanationText.innerHTML = schema.detailed_lecture || "Synthesizing academic lecture breakdown...";

// ============================================================================
// 2. TEXT-TO-SPEECH (WEB SPEECH API) ENGINE WITH ERROR HANDLING
// ============================================================================
let voices = [];
function populateVoices() {
  if (!window.speechSynthesis) return;
  try {
    voices = window.speechSynthesis.getVoices();
    DOM.voiceSelect.innerHTML = "";
    voices.forEach((v, index) => {
      const option = document.createElement('option');
      option.value = index;
      option.textContent = `${v.name} (${v.lang})`;
      if (v.default || v.lang.includes('en-GB') || v.lang.includes('en-US')) {
        option.selected = true;
      }
      DOM.voiceSelect.appendChild(option);
    });
  } catch (err) {
    console.error("❌ Error populating speech synthesis voices:", err);
  }
}

if (window.speechSynthesis) {
  populateVoices();
  window.speechSynthesis.onvoiceschanged = populateVoices;
}

DOM.speakBtn.addEventListener('click', () => {
  if (!window.speechSynthesis) {
    alert("Text-to-speech is not supported in your browser.");
    return;
  }
  window.speechSynthesis.cancel();
  
  try {
    const cleanText = DOM.explanationText.innerHTML.replace(/<[^>]*>?/gm, ''); 
    const utterance = new SpeechSynthesisUtterance(cleanText);
    const selectedVoiceIndex = parseInt(DOM.voiceSelect.value, 10);
    if (!isNaN(selectedVoiceIndex) && voices[selectedVoiceIndex]) {
      utterance.voice = voices[selectedVoiceIndex];
    }
    utterance.rate = 0.95;
    utterance.pitch = 1.0;
    window.speechSynthesis.speak(utterance);
  } catch (err) {
    console.error("❌ Speech synthesis execution failed:", err);
  }
});

DOM.stopSpeakBtn.addEventListener('click', () => {
  if (window.speechSynthesis) {
    window.speechSynthesis.cancel();
  }
});

// ============================================================================
// 3. DYNAMIC UNLIMITED CONDITIONS & PARAMETERS UI
// ============================================================================
const runtimeParams = {};
let isSimulationPaused = false;

// Append Playback Control Group
const playbackGroup = document.createElement('div');
playbackGroup.className = 'control-group';
playbackGroup.innerHTML = `
  <label>Simulation Playback</label>
  <div style="display: flex; gap: 8px;">
    <button id="pauseSimBtn" class="btn-action" style="flex:1; background: #3b82f6; font-size: 0.8rem;">⏸️ Pause</button>
    <button id="resetCyclesBtn" class="btn-outline" style="flex:1; font-size: 0.8rem;">🔄 Reset Clock</button>
  </div>
`;
DOM.controlsContainer.appendChild(playbackGroup);

document.getElementById('pauseSimBtn').addEventListener('click', (e) => {
  isSimulationPaused = !isSimulationPaused;
  e.target.textContent = isSimulationPaused ? "▶️ Resume" : "⏸️ Pause";
  e.target.style.background = isSimulationPaused ? "#10b981" : "#3b82f6";
});

document.getElementById('resetCyclesBtn').addEventListener('click', () => {
  cycles = 0;
  DOM.cycleMetric.textContent = cycles;
});

// Build dynamic parameters from schema definition
if (schema.parameters && Array.isArray(schema.parameters)) {
  schema.parameters.forEach(param => {
    runtimeParams[param.id] = param.default;
    const group = document.createElement('div');
    group.className = 'control-group';
    
    if (param.type === "select") {
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
      });
      
      group.appendChild(label);
      group.appendChild(select);
    } else {
      const label = document.createElement('label');
      label.innerHTML = `${param.label} <span id="val_${param.id}" style="color: #fff;">${param.default}</span>`;
      const slider = document.createElement('input');
      slider.type = 'range';
      slider.min = param.min !== undefined ? param.min : 1;
      slider.max = param.max !== undefined ? param.max : 10;
      slider.step = (slider.max - slider.min) > 20 ? "1" : "0.1";
      slider.value = param.default;
      
      slider.addEventListener('input', (e) => {
        const val = parseFloat(e.target.value);
        runtimeParams[param.id] = val;
        const valSpan = document.getElementById(`val_${param.id}`);
        if (valSpan) valSpan.textContent = val;
      });
      
      group.appendChild(label);
      group.appendChild(slider);
    }
    DOM.controlsContainer.appendChild(group);
  });
}

// ============================================================================
// 4. THREE.JS 3D SCENE, CAMERA, & LIGHTING SETUP
// ============================================================================
const scene = new THREE.Scene();
scene.background = new THREE.Color(CONFIG.clearColor);

const camera = new THREE.PerspectiveCamera(CONFIG.cameraFov, width / height, CONFIG.nearClip, CONFIG.farClip);
camera.position.set(0, 0, 16);

const renderer = new THREE.WebGLRenderer({ canvas: DOM.canvas, antialias: true, alpha: false, powerPreference: "high-performance" });
renderer.setSize(width, height);
renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
renderer.shadowMap.enabled = true;
renderer.shadowMap.type = THREE.PCFSoftShadowMap;

// Professional Lighting Suite
const ambientLight = new THREE.AmbientLight(0xffffff, 0.65);
scene.add(ambientLight);

const directionalLight = new THREE.DirectionalLight(0xffffff, 1.4);
directionalLight.position.set(15, 25, 20);
directionalLight.castShadow = true;
scene.add(directionalLight);

const pointLight = new THREE.PointLight(0x3b82f6, 2.0, 60);
pointLight.position.set(-15, -15, -15);
scene.add(pointLight);

// Orbit Controls Configuration
const controls = new THREE.OrbitControls(camera, renderer.domElement);
controls.enableDamping = true;
controls.dampingFactor = CONFIG.dampingFactor;
controls.minDistance = 2;
controls.maxDistance = 60;

// Debounced Window Resize Listener
let resizeTimeout;
window.addEventListener('resize', () => {
  clearTimeout(resizeTimeout);
  resizeTimeout = setTimeout(() => {
    width = DOM.container.clientWidth;
    height = DOM.container.clientHeight;
    camera.aspect = width / height;
    camera.updateProjectionMatrix();
    renderer.setSize(width, height);
  }, 100);
});

// ============================================================================
// 5. ENHANCED PROCEDURAL 3D SHAPE & MESH BUILDER
// ============================================================================
const nodeObjects = {};
const labels = [];
const nodeMeshesArray = [];

if (schema.nodes && Array.isArray(schema.nodes)) {
  schema.nodes.forEach(n => {
    let geometry;
    const shape = (n.shape_3d || 'sphere').toLowerCase();
    
    if (shape === 'organic' || shape === 'stomach') {
      geometry = new THREE.SphereGeometry(1.4, 32, 32);
      const positions = geometry.attributes.position;
      for (let i = 0; i < positions.count; i++) {
        let y = positions.getY(i);
        let x = positions.getX(i);
        let z = positions.getZ(i);
        positions.setX(i, x * (1 + y * 0.25)); 
        positions.setY(i, y * 1.15);         
        positions.setZ(i, z * 0.85);         
      }
      geometry.computeVertexNormals();
    } else if (shape === 'tube' || shape === 'intestine') {
      geometry = new THREE.TorusGeometry(1.3, 0.5, 16, 64, Math.PI * 1.6);
    } else if (shape === 'cube' || shape === 'server') {
      geometry = new THREE.BoxGeometry(1.8, 1.8, 1.8);
    } else {
      geometry = new THREE.SphereGeometry(1.3, 64, 64);
    }

    const material = new THREE.MeshStandardMaterial({ 
      color: n.color || '#3b82f6', 
      roughness: 0.22,
      metalness: 0.25,
      emissive: new THREE.Color(n.color || '#3b82f6').multiplyScalar(0.18)
    });
    
    const mesh = new THREE.Mesh(geometry, material);
    mesh.position.set(
      n.x !== undefined ? n.x : (Math.random() * 8 - 4), 
      n.y !== undefined ? n.y : (Math.random() * 8 - 4), 
      n.z !== undefined ? n.z : (Math.random() * 4 - 2)
    );
    
    mesh.userData = { 
      id: n.id, 
      label: n.label, 
      description: n.description || schema.description, 
      color: n.color 
    };
    
    scene.add(mesh);
    nodeObjects[n.id] = mesh;
    nodeMeshesArray.push(mesh);

    // HTML Overlay Label
    const label = document.createElement('div');
    label.className = 'node-label';
    label.textContent = n.label;
    DOM.labelsContainer.appendChild(label);
    labels.push({ element: label, mesh: mesh });
  });
}

// ============================================================================
// 6. 3D BEZIER CURVES FOR EDGES & CONNECTORS
// ============================================================================
const curves = [];
if (schema.edges && Array.isArray(schema.edges)) {
  schema.edges.forEach(e => {
    const fromMesh = nodeObjects[e.from];
    const toMesh = nodeObjects[e.to];
    
    if (fromMesh && toMesh) {
      const start = fromMesh.position;
      const end = toMesh.position;
      
      const midPoint = new THREE.Vector3().addVectors(start, end).multiplyScalar(0.5);
      midPoint.y += 1.8; 
      midPoint.z += 1.8;

      const curve = new THREE.QuadraticBezierCurve3(start, midPoint, end);
      curves.push({ curve: curve, edge: e });

      const points = curve.getPoints(60);
      const lineGeo = new THREE.BufferGeometry().setFromPoints(points);
      const lineMat = new THREE.LineBasicMaterial({ color: 0x334155, linewidth: 2, transparent: true, opacity: 0.6 });
      const splineObject = new THREE.Line(lineGeo, lineMat);
      scene.add(splineObject);
    }
  });
}

// ============================================================================
// 7. INTERACTIVE RAYCASTER & NODE INSPECTION CARD
// ============================================================================
const raycaster = new THREE.Raycaster();
const mouse = new THREE.Vector2();

const infoCard = document.createElement('div');
infoCard.style.cssText = "position:absolute; bottom:24px; right:24px; background:rgba(15,23,42,0.95); border:1px solid #3b82f6; padding:18px; border-radius:12px; color:#fff; max-width:300px; display:none; backdrop-filter:blur(10px); z-index:10; box-shadow:0 12px 30px rgba(0,0,0,0.7);";
infoCard.innerHTML = `<h4 id="cardTitle" style="margin:0 0 8px 0; color:#60a5fa; font-size:1rem;"></h4><p id="cardDesc" style="margin:0; font-size:0.85rem; color:#cbd5e1; line-height:1.6;"></p>`;
DOM.container.appendChild(infoCard);

DOM.container.addEventListener('click', (event) => {
  const rect = DOM.container.getBoundingClientRect();
  mouse.x = ((event.clientX - rect.left) / width) * 2 - 1;
  mouse.y = -((event.clientY - rect.top) / height) * 2 + 1;

  raycaster.setFromCamera(mouse, camera);
  const intersects = raycaster.intersectObjects(nodeMeshesArray);

  if (intersects.length > 0) {
    const clickedMesh = intersects[0].object;
    
    // Scale bump feedback animation
    clickedMesh.scale.set(1.25, 1.25, 1.25);
    setTimeout(() => { clickedMesh.scale.set(1, 1, 1); }, 250);
    
    // Display inspection card content
    document.getElementById('cardTitle').textContent = clickedMesh.userData.label;
    document.getElementById('cardDesc').textContent = clickedMesh.userData.description;
    infoCard.style.display = "block";
  } else {
    infoCard.style.display = "none";
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

  if (!isSimulationPaused) {
    let speedMod = 5;
    for (const key in runtimeParams) {
      if (typeof runtimeParams[key] === 'number') {
        speedMod = runtimeParams[key];
        break; 
      }
    }
    
    const spawnRate = Math.max(90, 1400 - (speedMod * 110));
    
    if (time - lastSpawnTime > spawnRate && curves.length > 0) {
      const randomCurveObj = curves[Math.floor(Math.random() * curves.length)];
      
      const pGeo = new THREE.SphereGeometry(0.16, 12, 12);
      const pMat = new THREE.MeshBasicMaterial({ color: randomCurveObj.edge.particle_color || '#ffffff' });
      const pMesh = new THREE.Mesh(pGeo, pMat);
      scene.add(pMesh);
      
      particles.push({
        mesh: pMesh,
        curve: randomCurveObj.curve,
        progress: 0,
        speed: CONFIG.particleBaseSpeed + (speedMod * 0.0009)
      });
      lastSpawnTime = time;
    }

    // Update Particles Along Curves
    for (let i = particles.length - 1; i >= 0; i--) {
      let p = particles[i];
      p.progress += p.speed;
      
      if (p.progress >= 1) {
        scene.remove(p.mesh);
        particles.splice(i, 1);
        cycles++;
        DOM.cycleMetric.textContent = cycles;
      } else {
        const point = p.curve.getPointAt(p.progress);
        p.mesh.position.copy(point);
      }
    }
  }

  // Update HTML Label Projections
  labels.forEach(l => {
    const vector = l.mesh.position.clone();
    vector.project(camera);
    
    const x = (vector.x * 0.5 + 0.5) * width;
    const y = (vector.y * -0.5 + 0.5) * height;
    
    if (vector.z < 1) { 
      l.element.style.opacity = 1;
      l.element.style.left = `${x}px`;
      l.element.style.top = `${y - 45}px`;
    } else {
      l.element.style.opacity = 0;
    }
  });

  renderer.render(scene, camera);
}

// Boot Simulation Loop
animate(0);