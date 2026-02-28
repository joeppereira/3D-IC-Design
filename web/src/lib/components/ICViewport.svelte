<script>
  import { Canvas } from '@threlte/core';
  import { OrbitControls, Grid } from '@threlte/extras';
  import * as THREE from 'three';

  let { thermalData = [] } = $props();
</script>

<div class="viewport">
  <Canvas>
    <OrbitControls />
    <ambientLight intensity={0.5} />
    <pointLight position={[10, 10, 10]} />

    <!-- 3D-IC Die Base -->
    <mesh position={[0, 0, 0]}>
      <boxGeometry args={[10, 0.5, 10]} />
      <meshStandardMaterial color="#222" />
    </mesh>

    <!-- Thermal Chimney (Instanced Voxels) -->
    {#each Array(5) as _, layer}
      <mesh position={[0, (layer + 1) * 0.6, 0]}>
        <boxGeometry args={[8, 0.1, 8]} />
        <meshStandardMaterial 
          color={layer < 2 ? "#ff4400" : "#0088ff"} 
          transparent 
          opacity={0.6} 
        />
      </mesh>
    {/each}

    <Grid infiniteGrid sectionSize={1} />
  </Canvas>
</div>

<style>
  .viewport {
    height: 400px;
    background: #000;
    border-radius: 8px;
    border: 1px solid #333;
  }
</style>
