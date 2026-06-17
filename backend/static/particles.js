let particleScene, particleCamera, particleRenderer, particleSystem, connectionLines;
let pMouseX = 0, pMouseY = 0, pTargetMX = 0, pTargetMY = 0;
let pTime = 0;

function initParticles() {
  const container = document.getElementById('particle-bg');
  if (!container) return;

  const w = window.innerWidth;
  const h = window.innerHeight;
  if (w < 768) return;

  particleScene = new THREE.Scene();

  particleCamera = new THREE.PerspectiveCamera(75, w / h, 0.1, 1000);
  particleCamera.position.z = 30;

  particleRenderer = new THREE.WebGLRenderer({ alpha: true, antialias: true });
  particleRenderer.setSize(w, h);
  particleRenderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
  container.appendChild(particleRenderer.domElement);

  const count = 2000;
  const pos = new Float32Array(count * 3);
  const colors = new Float32Array(count * 3);
  const sizes = new Float32Array(count);
  const velocities = [];

  for (let i = 0; i < count; i++) {
    const radius = 5 + Math.random() * 25;
    const theta = Math.random() * Math.PI * 2;
    const phi = Math.acos(2 * Math.random() - 1);
    pos[i * 3] = radius * Math.sin(phi) * Math.cos(theta);
    pos[i * 3 + 1] = radius * Math.sin(phi) * Math.sin(theta);
    pos[i * 3 + 2] = radius * Math.cos(phi);

    const t = Math.random();
    colors[i * 3] = 0.2 + t * 0.3;
    colors[i * 3 + 1] = 0.2 + t * 0.2;
    colors[i * 3 + 2] = 0.6 + t * 0.4;

    sizes[i] = 0.02 + Math.random() * 0.06;
    velocities.push({
      x: (Math.random() - 0.5) * 0.002,
      y: (Math.random() - 0.5) * 0.002,
      z: (Math.random() - 0.5) * 0.002,
      phase: Math.random() * Math.PI * 2,
      amp: 0.1 + Math.random() * 0.3,
    });
  }

  const geo = new THREE.BufferGeometry();
  geo.setAttribute('position', new THREE.BufferAttribute(pos, 3));
  geo.setAttribute('color', new THREE.BufferAttribute(colors, 3));
  geo.setAttribute('size', new THREE.BufferAttribute(sizes, 1));

  const mat = new THREE.PointsMaterial({
    size: 0.08,
    vertexColors: true,
    transparent: true,
    opacity: 0.7,
    blending: THREE.AdditiveBlending,
    depthWrite: false,
    sizeAttenuation: true,
  });

  particleSystem = new THREE.Points(geo, mat);
  particleScene.add(particleSystem);

  const connMat = new THREE.LineBasicMaterial({
    color: 0x3b82f6,
    transparent: true,
    opacity: 0.03,
  });

  connectionLines = new THREE.Group();
  const connGeo = new THREE.BufferGeometry();
  const connPositions = [];
  const indices = [];

  for (let i = 0; i < count; i++) {
    connPositions.push(
      new THREE.Vector3(pos[i * 3], pos[i * 3 + 1], pos[i * 3 + 2])
    );
  }

  for (let i = 0; i < count; i++) {
    for (let j = i + 1; j < count; j++) {
      const dx = connPositions[i].x - connPositions[j].x;
      const dy = connPositions[i].y - connPositions[j].y;
      const dz = connPositions[i].z - connPositions[j].z;
      const dist = Math.sqrt(dx * dx + dy * dy + dz * dz);
      if (dist < 4 && Math.random() < 0.02) {
        const cg = new THREE.BufferGeometry().setFromPoints([
          connPositions[i],
          connPositions[j],
        ]);
        connectionLines.add(new THREE.Line(cg, connMat));
      }
    }
  }
  particleScene.add(connectionLines);

  window.addEventListener('mousemove', (e) => {
    pTargetMX = (e.clientX / w - 0.5) * 2;
    pTargetMY = (e.clientY / h - 0.5) * 2;
  });

  function animate() {
    requestAnimationFrame(animate);
    pTime += 0.003;

    pMouseX += (pTargetMX - pMouseX) * 0.02;
    pMouseY += (pTargetMY - pMouseY) * 0.02;

    const positions = particleSystem.geometry.attributes.position.array;
    for (let i = 0; i < positions.length; i += 3) {
      const idx = i / 3;
      const v = velocities[idx];
      positions[i] += Math.sin(pTime + v.phase) * v.amp * 0.002;
      positions[i + 1] += Math.cos(pTime * 0.7 + v.phase) * v.amp * 0.002;
      positions[i + 2] += Math.sin(pTime * 0.5 + v.phase * 1.3) * v.amp * 0.002;
    }
    particleSystem.geometry.attributes.position.needsUpdate = true;

    particleSystem.rotation.y += 0.0003;
    particleSystem.rotation.x += 0.0001;
    connectionLines.rotation.y += 0.0003;
    connectionLines.rotation.x += 0.0001;

    particleCamera.position.x += (pMouseX * 0.3 - particleCamera.position.x) * 0.01;
    particleCamera.position.y += (-pMouseY * 0.3 - particleCamera.position.y) * 0.01;
    particleCamera.lookAt(0, 0, 0);

    particleRenderer.render(particleScene, particleCamera);
  }
  animate();

  window.addEventListener('resize', () => {
    const nw = window.innerWidth;
    const nh = window.innerHeight;
    particleCamera.aspect = nw / nh;
    particleCamera.updateProjectionMatrix();
    particleRenderer.setSize(nw, nh);
  });
}

document.addEventListener('DOMContentLoaded', () => {
  if (typeof THREE !== 'undefined') {
    setTimeout(initParticles, 600);
  }
});
