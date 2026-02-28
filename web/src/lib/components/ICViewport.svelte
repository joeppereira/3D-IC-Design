<script>
  import { Canvas } from '@threlte/core';
  import { OrbitControls, Grid } from '@threlte/extras';
  import * as THREE from 'three';

  let { thermalData = [] } = $props();
</script>

<div class="viewport">
  <Canvas>
    <OrbitControls />
    <ambientLight intensity={0.2} />
    <pointLight position={[10, 10, 10]} intensity={1.5} />
    <directionalLight position={[-5, 5, 5]} intensity={0.5} />

    <!-- 3D-IC Die Base (Low Profile) -->
    <mesh position={[0, -0.25, 0]}>
      <boxGeometry args={[10, 0.2, 10]} />
      <meshStandardMaterial color="#111" roughness={0.5} />
    </mesh>

    <!-- The 10-Die Stack (Simplified) -->
    {#each Array(5) as _, layer}
      <mesh position={[0, layer * 0.4, 0]}>
        <boxGeometry args={[8, 0.05, 8]} />
        <meshStandardMaterial 
          color={layer === 4 ? "#00e5ff" : "#2a2a2a"} 
          transparent 
          opacity={layer === 4 ? 0.8 : 0.4} 
        />
      </mesh>
    {/each}

    <!-- Vertical Power Vias (Meshi Teal) -->
    {#each Array(8) as _, i}
      <mesh position={[Math.sin(i) * 3, 0.8, Math.cos(i) * 3]}>
        <cylinderGeometry args={[0.02, 0.02, 2]} />
        <meshStandardMaterial color="#00e5ff" emissive="#00e5ff" emissiveIntensity={0.5} />
      </mesh>
    {/each}

    <!-- Clean Floor Grid -->
    <Grid infiniteGrid sectionSize={2} fadeDistance={30} sectionColor="#2a2a2a" cellColor="#1a1a1a" />
  </Canvas>
</div>

<style>
  .viewport {
    height: 100%;
    width: 100%;
    background: transparent;
  }
</style>