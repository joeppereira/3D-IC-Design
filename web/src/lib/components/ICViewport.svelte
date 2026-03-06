<script>
  import { onMount, onDestroy } from 'svelte';
  import * as THREE from 'three';
  import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls';

  let container;
  let renderer, scene, camera, controls;
  let frameId;

  onMount(() => {
    console.log("🧊 [3DIC] Native Viewport Initializing (v4.2.2)...");

    // 1. SCENE & CAMERA
    scene = new THREE.Scene();
    camera = new THREE.PerspectiveCamera(45, container.clientWidth / container.clientHeight, 0.1, 1000);
    camera.position.set(15, 15, 15);

    // 2. RENDERER
    renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
    renderer.setSize(container.clientWidth, container.clientHeight);
    renderer.setPixelRatio(window.devicePixelRatio);
    container.appendChild(renderer.domElement);

    // 3. CONTROLS
    controls = new OrbitControls(camera, renderer.domElement);
    controls.enableDamping = true;
    controls.target.set(0, 1, 0);

    // 4. LIGHTING
    const ambient = new THREE.AmbientLight(0xffffff, 0.2);
    scene.add(ambient);

    const point = new THREE.PointLight(0xff00ff, 1.5);
    point.position.set(10, 10, 10);
    scene.add(point);

    const dir = new THREE.DirectionalLight(0xffffff, 0.5);
    dir.position.set(-5, 5, 5);
    scene.add(dir);

    // 5. 3D-IC DIE BASE
    const baseGeo = new THREE.BoxGeometry(10, 0.2, 10);
    const baseMat = new THREE.MeshStandardMaterial({ color: 0x111111, roughness: 0.5 });
    const base = new THREE.Mesh(baseGeo, baseMat);
    base.position.y = -0.25;
    scene.add(base);

    // 6. THE 10-DIE STACK (Pink/Purple)
    for (let i = 0; i < 5; i++) {
      const dieGeo = new THREE.BoxGeometry(8, 0.08, 8);
      const dieMat = new THREE.MeshStandardMaterial({ 
        color: i === 4 ? 0xff00ff : 0x222222, 
        transparent: true, 
        opacity: i === 4 ? 0.9 : 0.4,
        emissive: i === 4 ? 0xff00ff : 0x000000,
        emissiveIntensity: i === 4 ? 0.4 : 0
      });
      const die = new THREE.Mesh(dieGeo, dieMat);
      die.position.y = i * 0.6;
      scene.add(die);
    }

    // 7. VERTICAL POWER VIAS (Neon Pink)
    for (let i = 0; i < 12; i++) {
      const angle = (i / 12) * Math.PI * 2;
      const viaGeo = new THREE.CylinderGeometry(0.03, 0.03, 2.5);
      const viaMat = new THREE.MeshStandardMaterial({ color: 0xff00ff, emissive: 0xff00ff, emissiveIntensity: 0.8 });
      const via = new THREE.Mesh(viaGeo, viaMat);
      via.position.set(Math.sin(angle) * 3.5, 1.2, Math.cos(angle) * 3.5);
      scene.add(via);
    }

    // 8. ANIMATION LOOP
    const animate = () => {
      frameId = requestAnimationFrame(animate);
      controls.update();
      renderer.render(scene, camera);
    };
    animate();

    // 9. RESIZE HANDLER
    const onResize = () => {
      camera.aspect = container.clientWidth / container.clientHeight;
      camera.updateProjectionMatrix();
      renderer.setSize(container.clientWidth, container.clientHeight);
    };
    window.addEventListener('resize', onResize);

    return () => {
      window.removeEventListener('resize', onResize);
      cancelAnimationFrame(frameId);
    };
  });
</script>

<div bind:this={container} class="viewport"></div>

<style>
  .viewport {
    height: 100%;
    width: 100%;
    background: transparent;
    cursor: grab;
  }
  .viewport:active {
    cursor: grabbing;
  }
</style>
