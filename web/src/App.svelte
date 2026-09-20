<script>
  import { onMount, tick } from 'svelte';
  import ICViewport from './lib/components/ICViewport.svelte';
  import WaveformViewer from './lib/components/WaveformViewer.svelte';
  import { GeminiService } from './lib/agents/GeminiService';

  const VERSION = "v5.8.2-SANITY-FIX";
  
  // --- UI STATE ---
  let showWaveform = $state(false);
  let showEM = $state(false);
  let showTransient = $state(false);
  let showComparison = $state(false);
  let isThinking = $state(false);
  let activeBrain = $state("EXPERT");
  let geminiKey = $state("");
  let geminiService = $state(new GeminiService());
  
  // Data Mocks
  let emData = $state({ next: -42.5, fext: -48.2, tax: 0.042 });
  let tjHistory = $state([25, 45, 78, 98, 104, 102, 99]);
  let comparisonData = $state({ baseline: { tj: 105, eye: 0.48, kv: 0.85 }, champion: { tj: 98.5, eye: 0.52, kv: 0.60 } });

  let userInput = $state("");
  let messages = $state([
    { id: 'msg-1', type: 'agent', brain: 'SYSTEM', text: "Hello. I am the 3DIC-X Architectural Explorer. System Sanity Check complete. How shall we proceed?" }
  ]);
  
  let chatMessagesContainer; 
  let messageCounter = 0;
  function getUniqueId() { return `msg-${Date.now()}-${++messageCounter}`; }

  onMount(() => {
    const savedKey = localStorage.getItem('3dic_gemini_key');
    if (savedKey) { geminiKey = savedKey; geminiService.apiKey = savedKey; activeBrain = "CLOUD"; }
    scrollToBottom();
  });

  async function scrollToBottom() { await tick(); if (chatMessagesContainer) { chatMessagesContainer.scrollTop = chatMessagesContainer.scrollHeight; } }

  function getExpertResponse(text) {
    const lower = text.toLowerCase();
    if (lower.includes('em') || lower.includes('maxwell')) { showEM = true; return "Launching Maxwell 3D Field Solver (50nm Res)..."; }
    if (lower.includes('burst') || lower.includes('transient')) { showTransient = true; return "Initiating 1000µs Thermal Burst Simulation..."; }
    if (lower.includes('compare')) { showComparison = true; return "Running side-by-side SOTA vs. Legacy Audit..."; }
    if (lower.includes('ingest') || lower.includes('ansys')) return "Industrial Ingestor active. Reading external .csv and .sp references.";
    return null;
  }

  async function handleSend(event) {
    if (event) event.preventDefault();
    const text = userInput.trim();
    if (text && !isThinking) {
      messages = [...messages, { id: getUniqueId(), type: 'user', text }];
      userInput = ""; isThinking = true; scrollToBottom();
      const lower = text.toLowerCase();

      if (lower.startsWith('key ')) {
        const key = text.split(' ')[1];
        localStorage.setItem('3dic_gemini_key', key); geminiKey = key; geminiService.apiKey = key; activeBrain = "CLOUD";
        isThinking = false; triggerAgentResponse("✅ API Key accepted.", "SYSTEM"); return;
      }

      setTimeout(async () => {
        let response = getExpertResponse(text);
        let usedBrain = "EXPERT";
        if (!response && activeBrain === "CLOUD") {
          response = await geminiService.generate(text, "3DIC-X v5.8, 3nm GAA.");
          usedBrain = "CLOUD";
        }
        if (response) {
          messages = [...messages, { id: getUniqueId(), type: 'agent', brain: usedBrain, text: response }];
          isThinking = false; scrollToBottom();
        }
      }, 800);
    }
  }

  function triggerAgentResponse(text, brain) {
    messages = [...messages, { id: getUniqueId(), type: 'agent', brain, text }];
    scrollToBottom();
  }

  function exportNetlist() {
    triggerAgentResponse("📐 Exporting 'top_smart.sp' netlist for external validation.", "SYSTEM");
  }
</script>

<div class="app-container">
  <!-- VIEWPORT SECTION -->
  <section class="viewport-section">
    <div class="meshi-logo"><div class="logo-circle"></div><div class="logo-text">3DIC-X</div></div>
    <ICViewport />
    
    <div class="tool-layer">
      {#if showWaveform}<div class="floating-panel"><div class="panel-header"><span>SURFER</span><button onclick={() => showWaveform = false}>×</button></div><WaveformViewer /></div>{/if}
      
      {#if showEM}
        <div class="floating-panel em">
          <div class="panel-header"><span>MAXWELL EM (HIGH-RES)</span><button onclick={() => showEM = false}>×</button></div>
          <div class="em-content">
            <div class="matrix">
              <div class="stat"><span class="label">NEXT:</span><span class="value accent">{emData.next} dB</span></div>
              <div class="stat"><span class="label">FEXT:</span><span class="value accent">{emData.fext} dB</span></div>
            </div>
          </div>
        </div>
      {/if}

      {#if showTransient}
        <div class="floating-panel transient">
          <div class="panel-header"><span>TRANSIENT ROI (50nm)</span><button onclick={() => showTransient = false}>×</button></div>
          <div class="transient-content">
            <div class="chart-mock">
              {#each tjHistory as tj}<div class="bar" style="height: {tj}%"></div>{/each}
            </div>
          </div>
        </div>
      {/if}

      {#if showComparison}
        <div class="floating-panel comparison">
          <div class="panel-header"><span>SOTA VS LEGACY AUDIT</span><button onclick={() => showComparison = false}>×</button></div>
          <div class="comparison-grid">
            <div class="cell-label">Peak Tj</div><div class="cell-val">{comparisonData.champion.tj}°C</div>
            <div class="cell-label">Eye UI</div><div class="cell-val">{comparisonData.champion.eye}</div>
          </div>
        </div>
      {/if}
    </div>
    
    <div class="status-bar">
      <span>Status: 🟢 {VERSION}</span>
      <span class="accuracy-badge">Level 2: Exploratory</span>
      <button class="export-btn" onclick={exportNetlist}>EXPORT FOR VAL</button>
    </div>
  </section>

  <!-- CHAT SECTION -->
  <section class="chat-section">
    <div class="chat-header">
      <h2>ARCHITECT</h2>
      <div style="display: flex; gap: 8px; margin-top: 4px;">
        <span class="brain-badge {activeBrain === 'EXPERT' ? 'active' : ''}">EXPERT</span>
        <span class="brain-badge {activeBrain === 'CLOUD' ? 'active' : ''} {!geminiKey ? 'waiting' : ''}">CLOUD</span>
      </div>
    </div>
    <div class="chat-messages" bind:this={chatMessagesContainer}>
      {#each messages as msg (msg.id)}
        <div class="message-wrapper {msg.type}">
          <div class="avatar {msg.type}">{msg.type === 'agent' ? 'A' : 'U'}</div>
          <div class="message-bubble">{msg.text}<div class="engine-tag">Engine: {msg.brain}</div></div>
        </div>
      {/each}
      {#if isThinking}<div class="typing">Architect is thinking...</div>{/if}
    </div>
    <form class="chat-input-container" onsubmit={handleSend}><div class="input-wrapper"><input type="text" placeholder="Message the Architect..." bind:value={userInput} autocomplete="off" /><button type="submit" class="send-btn">➔</button></div></form>
  </section>
</div>

<style>
  :root { --bg-primary: #050505; --bg-secondary: #0f0f0f; --accent-pink: #ff00ff; --accent-purple: #9d00ff; --accent-gradient: linear-gradient(135deg, #ff00ff 0%, #9d00ff 100%); --text-primary: #ffffff; --text-secondary: #a0a0a0; --border: #1a1a1a; }
  :global(body) { margin: 0; padding: 0; background-color: var(--bg-primary); color: var(--text-primary); font-family: sans-serif; overflow: hidden; }
  .app-container { display: flex; height: 100vh; width: 100vw; }
  .viewport-section { flex: 1; position: relative; background: radial-gradient(circle at 30% 30%, #1a0a2a 0%, #050505 100%); }
  .status-bar { position: absolute; bottom: 40px; left: 40px; color: #666; font-size: 0.8rem; display: flex; gap: 24px; align-items: center; }
  .export-btn { background: transparent; border: 1px solid #333; color: #666; padding: 2px 10px; border-radius: 4px; font-size: 0.6rem; cursor: pointer; transition: all 0.3s; }
  .export-btn:hover { border-color: #ff00ff; color: #ff00ff; box-shadow: 0 0 10px rgba(255, 0, 255, 0.2); }
  .accuracy-badge { font-size: 0.6rem; color: #ff00ff; border: 1px solid #ff00ff; padding: 2px 8px; border-radius: 10px; font-weight: 800; }
  .chat-section { width: 500px; background: var(--bg-secondary); border-left: 1px solid var(--border); display: flex; flex-direction: column; }
  .chat-header { padding: 24px 32px; border-bottom: 1px solid var(--border); }
  .brain-badge { font-size: 0.5rem; padding: 2px 6px; border-radius: 10px; border: 1px solid #333; color: #666; font-weight: 800; }
  .brain-badge.active { background: var(--accent-gradient); border: none; color: white; }
  .brain-badge.waiting { border-color: #ff00ff; color: #ff00ff; animation: pulse 2s infinite; }
  @keyframes pulse { 0% { opacity: 0.4; } 50% { opacity: 1; } 100% { opacity: 0.4; } }
  .chat-messages { flex: 1; padding: 32px; overflow-y: auto; display: flex; flex-direction: column; gap: 32px; scroll-behavior: smooth; }
  .message-wrapper { display: flex; gap: 16px; width: 100%; }
  .message-wrapper.user { flex-direction: row-reverse; }
  .avatar { width: 36px; height: 36px; border-radius: 50%; display: flex; align-items: center; justify-content: center; font-weight: 700; color: white; font-size: 0.8rem; }
  .avatar.agent { background: var(--accent-gradient); }
  .avatar.user { background: #333; }
  .message-bubble { max-width: 80%; padding: 16px 20px; border-radius: 20px; font-size: 1rem; line-height: 1.5; white-space: pre-wrap; position: relative; }
  .agent .message-bubble { background: #1a1a1a; color: #fff; border: 1px solid #222; }
  .user .message-bubble { background: var(--accent-gradient); color: #fff; }
  .engine-tag { font-size: 0.5rem; margin-top: 8px; color: #444; text-transform: uppercase; }
  .typing { font-size: 0.8rem; color: var(--accent-pink); margin-top: -16px; margin-left: 52px; font-style: italic; }
  .chat-input-container { padding: 32px; background: #080808; border-top: 1px solid var(--border); }
  .input-wrapper { display: flex; align-items: center; gap: 12px; background: #151515; padding: 12px 20px; border-radius: 28px; border: 2px solid #222; }
  .input-wrapper input { flex: 1; background: transparent; border: none; color: #fff; font-size: 1.1rem; outline: none; }
  .send-btn { background: var(--accent-gradient); border: none; width: 44px; height: 44px; border-radius: 50%; cursor: pointer; color: white; display: flex; align-items: center; justify-content: center; }
  .meshi-logo { position: absolute; top: 40px; left: 40px; display: flex; align-items: center; gap: 16px; z-index: 10; }
  .logo-circle { width: 44px; height: 44px; background: var(--accent-gradient); border-radius: 50%; }
  .logo-text { font-weight: 800; font-size: 1.8rem; color: #ffffff; }
  .tool-layer { position: absolute; top: 120px; left: 40px; right: 40px; bottom: 120px; pointer-events: none; display: flex; flex-direction: column; gap: 32px; z-index: 50; }
  .floating-panel { pointer-events: auto; background: rgba(10, 10, 10, 0.98); backdrop-filter: blur(40px); border: 1px solid #222; border-radius: 16px; overflow: hidden; box-shadow: 0 20px 80px rgba(0,0,0,1); max-width: 650px; }
  .panel-header { background: #1a1a1a; padding: 12px 24px; display: flex; justify-content: space-between; align-items: center; font-size: 0.8rem; color: #ff00ff; border-bottom: 1px solid #222; }
  .panel-header button { background: none; border: none; color: #666; cursor: pointer; font-size: 1.5rem; }
  .em-content, .transient-content, .comparison-grid { padding: 24px; }
  .matrix { display: flex; gap: 16px; }
  .stat { display: flex; flex-direction: column; }
  .stat .label { font-size: 0.6rem; color: #666; }
  .stat .value { font-family: monospace; color: #fff; }
  .stat .accent { color: #ff00ff; }
  .chart-mock { height: 100px; display: flex; align-items: flex-end; gap: 4px; }
  .bar { flex: 1; background: var(--accent-gradient); }
  .comparison-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }
</style>