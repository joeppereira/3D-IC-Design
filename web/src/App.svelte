<script>
  import { onMount, tick } from 'svelte';
  import ICViewport from './lib/components/ICViewport.svelte';
  import WaveformViewer from './lib/components/WaveformViewer.svelte';
  import { GeminiService } from './lib/agents/GeminiService';

  const VERSION = "v5.2.0-SOTA-GOVERNED";
  
  // --- UI STATE ---
  let showWaveform = $state(false);
  let showLayout = $state(false);
  let showSOTA = $state(false); 
  let isPaused = $state(false);
  let isThinking = $state(false);
  let activeBrain = $state("EXPERT"); 
  let currentFitness = $state(0.62);
  let gepaBaseline = 0.62;
  
  let geminiKey = $state(""); 
  let geminiService = $state(new GeminiService());
  
  let userInput = $state("");
  let messages = $state([
    { id: 'msg-1', type: 'agent', brain: 'SYSTEM', text: "Hello. I am the Governed Architect. I've integrated SkyDiscover SOTA with User Intervention hooks. Type 'evolve' to begin or 'pause' to audit my progress." }
  ]);
  
  let chatMessagesContainer; 
  let messageCounter = 0;
  function getUniqueId() { return `msg-${Date.now()}-${++messageCounter}`; }

  onMount(() => {
    const savedKey = localStorage.getItem('3dic_gemini_key');
    if (savedKey) { geminiKey = savedKey; geminiService.apiKey = savedKey; activeBrain = "CLOUD"; }
    scrollToBottom();
  });

  async function scrollToBottom() { await tick(); if (chatMessagesContainer) chatMessagesContainer.scrollTop = chatMessagesContainer.scrollHeight; }

  function togglePause() {
    isPaused = !isPaused;
    const status = isPaused ? "Evolution Paused. Waiting for User Audit." : "Evolution Resumed. Searching Pareto space...";
    triggerAgentResponse(status, "SYSTEM");
  }

  function handleSend(event) {
    if (event) event.preventDefault();
    const text = userInput.trim();
    if (text && !isThinking) {
      messages = [...messages, { id: getUniqueId(), type: 'user', text }];
      userInput = ""; isThinking = true; scrollToBottom();
      const lower = text.toLowerCase();

      // 1. INTERVENTION COMMANDS
      if (lower.includes('evolve') || lower.includes('sota')) {
        showSOTA = true; isThinking = false; isPaused = false;
        triggerAgentResponse("🚀 Initializing SkyDiscover AdaEvolve. Target: 29% KV-cache reduction.", "SYSTEM");
        let interval = setInterval(() => {
          if (!isPaused && currentFitness < 0.94) currentFitness += 0.01;
          if (currentFitness >= 0.94) clearInterval(interval);
        }, 1000);
        return;
      }

      if (lower.includes('pause')) { togglePause(); isThinking = false; return; }

      // 2. DISPATCH
      setTimeout(async () => {
        let response = "";
        let usedBrain = activeBrain;

        if (activeBrain === "CLOUD") {
          response = await geminiService.generate(text, "Search King v5.0, SkyDiscover SOTA.");
        } else {
          response = "Understood. I am adjusting my internal design rules based on your strategic steering.";
        }

        messages = [...messages, { id: getUniqueId(), type: 'agent', brain: usedBrain, text: response }];
        isThinking = false; scrollToBottom();
      }, 800);
    }
  }

  function triggerAgentResponse(text, brain) {
    messages = [...messages, { id: getUniqueId(), type: 'agent', brain, text }];
    scrollToBottom();
  }
</script>

<div class="app-container">
  <section class="viewport-section">
    <div class="meshi-logo"><div class="logo-circle"></div><div class="logo-text">3DIC Design</div></div>
    <ICViewport />
    
    <div class="tool-layer">
      {#if showSOTA}
        <div class="floating-panel sota">
          <div class="panel-header">
            <span>SKYDISCOVER SOTA ENGINE</span>
            <div style="display: flex; gap: 8px;">
              <button class="int-btn" onclick={togglePause}>{isPaused ? '▶ RESUME' : '⏸ PAUSE'}</button>
              <button onclick={() => showSOTA = false}>×</button>
            </div>
          </div>
          <div class="sota-metrics">
            <div class="metric-row"><span>Fitness:</span><span class="value">{currentFitness.toFixed(4)}</span></div>
            <div class="metric-row"><span>Gain over GEPA:</span><span class="value accent">+{( (currentFitness - gepaBaseline)/gepaBaseline*100 ).toFixed(1)}%</span></div>
            <div class="progress-bar-container"><div class="sota-progress" style="width: {currentFitness * 100}%;"></div></div>
            <div class="sota-log">
              {isPaused ? "[USER INTERVENTION] Waiting for audit feedback..." : "[AdaEvolve] Exploring 3nm Hybrid-Bonding pitch..."}<br/>
              [System] Target: 29% KV-cache pressure reduction active.
            </div>
          </div>
        </div>
      {/if}
    </div>
    
    <div style="position: absolute; bottom: 40px; left: 40px; color: #666; font-size: 0.8rem; letter-spacing: 0.1rem; text-transform: uppercase;">Status: 🟢 {VERSION}</div>
  </section>

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

    <form class="chat-input-container" onsubmit={handleSend}>
      <div class="input-wrapper">
        <input type="text" placeholder="Message the Architect..." bind:value={userInput} autocomplete="off" />
        <button type="submit" class="send-btn">➔</button>
      </div>
    </form>
  </section>
</div>

<style>
  :root { --bg-primary: #050505; --bg-secondary: #0f0f0f; --accent-pink: #ff00ff; --accent-purple: #9d00ff; --accent-gradient: linear-gradient(135deg, #ff00ff 0%, #9d00ff 100%); --text-primary: #ffffff; --text-secondary: #a0a0a0; --border: #1a1a1a; }
  :global(body) { margin: 0; padding: 0; background-color: var(--bg-primary); color: var(--text-primary); font-family: sans-serif; overflow: hidden; }
  .app-container { display: flex; height: 100vh; width: 100vw; }
  .viewport-section { flex: 1; position: relative; background: radial-gradient(circle at 30% 30%, #1a0a2a 0%, #050505 100%); }
  .chat-section { width: 500px; background: var(--bg-secondary); border-left: 1px solid var(--border); display: flex; flex-direction: column; }
  .chat-header { padding: 24px 32px; border-bottom: 1px solid var(--border); }
  .brain-badge { font-size: 0.5rem; padding: 2px 6px; border-radius: 10px; border: 1px solid #333; color: #666; font-weight: 800; letter-spacing: 0.05rem; }
  .brain-badge.active { background: var(--accent-gradient); border: none; color: white; box-shadow: 0 0 10px rgba(255, 0, 255, 0.3); }
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
  .send-btn { background: var(--accent-gradient); border: none; width: 44px; height: 44px; border-radius: 50%; cursor: pointer; color: white; display: flex; align-items: center; justify-content: center; font-size: 1.2rem; }
  .meshi-logo { position: absolute; top: 40px; left: 40px; display: flex; align-items: center; gap: 16px; z-index: 10; }
  .logo-circle { width: 44px; height: 44px; background: var(--accent-gradient); border-radius: 50%; }
  .logo-text { font-weight: 800; font-size: 1.8rem; color: #ffffff; }
  
  /* SOTA & INTERVENTION STYLES */
  .tool-layer { position: absolute; top: 120px; left: 40px; right: 40px; bottom: 120px; pointer-events: none; display: flex; flex-direction: column; gap: 32px; z-index: 50; }
  .floating-panel { pointer-events: auto; background: rgba(10, 10, 10, 0.98); backdrop-filter: blur(40px); border: 1px solid #222; border-radius: 16px; overflow: hidden; box-shadow: 0 20px 80px rgba(0,0,0,1); max-width: 650px; }
  .panel-header { background: #1a1a1a; padding: 12px 24px; display: flex; justify-content: space-between; align-items: center; font-size: 0.8rem; color: #ff00ff; border-bottom: 1px solid #222; }
  .panel-header button { background: none; border: none; color: #666; cursor: pointer; font-size: 1.5rem; }
  .int-btn { background: #222; color: #fff; border: 1px solid #333; padding: 4px 12px; border-radius: 12px; font-size: 0.6rem; font-weight: 800; cursor: pointer; }
  .int-btn:hover { background: #333; border-color: #ff00ff; }
  .sota-metrics { padding: 32px; display: flex; flex-direction: column; gap: 16px; }
  .metric-row { display: flex; justify-content: space-between; font-family: 'JetBrains Mono', monospace; font-size: 1.1rem; }
  .metric-row .accent { color: #ff00ff; font-weight: 800; }
  .progress-bar-container { height: 8px; background: #222; border-radius: 4px; overflow: hidden; margin: 16px 0; }
  .sota-progress { height: 100%; background: var(--accent-gradient); transition: width 0.5s ease-out; }
  .sota-log { background: #000; padding: 16px; font-family: monospace; font-size: 0.8rem; color: #00ff00; border-radius: 8px; line-height: 1.6; min-height: 100px; }
</style>
