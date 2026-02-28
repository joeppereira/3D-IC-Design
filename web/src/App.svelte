<script>
  import ICViewport from './lib/components/ICViewport.svelte';
  import WaveformViewer from './lib/components/WaveformViewer.svelte';
  import { PhysicsAgent } from './lib/agents/PhysicsAgent';
  import { RemoteSensingAgent } from './lib/agents/RemoteSensingAgent';
  import { onMount } from 'svelte';

  let physics = new PhysicsAgent();
  let remote = new RemoteSensingAgent();
  let agentStatus = $state("Monitoring Physics...");
  let agentLogs = $state([]);

  onMount(async () => {
    // Start background telemetry monitoring
    await remote.processLog("OpenROAD: Global Route Initialized");
    agentLogs = remote.getTraceabilityReport();
    
    // Run an initial agent design check
    const result = await physics.analyzeLink({ jitter: 0.22 });
    if (result.action === "REPLACE_DECAP") {
      agentStatus = `⚠️ Action Needed: ${result.suggestion}`;
    }
  });
</script>

<main>
  <header>
    <h1>🛰️ 3D-IC Designer v4.0 (Enterprise Explorer)</h1>
    <div class="agent-panel">
      <strong>Agent Status:</strong> {agentStatus}
    </div>
  </header>

  <div class="dashboard-grid">
    <section class="left">
      <ICViewport />
      <div class="log-view">
        <h3>🛰️ Traceable Telemetry (Fluent Bit)</h3>
        <ul>
          {#each agentLogs as log}
            <li>{log}</li>
          {/each}
        </ul>
      </div>
    </section>

    <section class="right">
      <WaveformViewer />
      <div class="layout-viewer-mock">
        <h3>📐 KLayout GDSII Viewer (Wasm)</h3>
        <div class="canvas-placeholder">
          [GDSII Merge: Logic-SRAM Hybrid Bonds]
        </div>
      </div>
    </section>
  </div>
</main>

<style>
  :global(body) { background: #0a0a0a; color: #eee; font-family: system-ui; }
  main { padding: 1rem; }
  header { display: flex; justify-content: space-between; align-items: center; border-bottom: 1px solid #333; padding-bottom: 1rem; }
  .agent-panel { background: #222; padding: 0.5rem 1rem; border-radius: 4px; border-left: 4px solid #0088ff; }
  .dashboard-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 1.5rem; margin-top: 1rem; }
  .log-view { margin-top: 1rem; background: #111; padding: 1rem; height: 200px; overflow-y: auto; font-family: monospace; border: 1px solid #222; }
  .canvas-placeholder { height: 250px; background: #111; border: 1px dashed #444; display: flex; align-items: center; justify-content: center; }
</style>
