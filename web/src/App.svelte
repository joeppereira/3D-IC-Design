<script>
  import './lib/meshi-theme.css';
  import ICViewport from './lib/components/ICViewport.svelte';
  import { onMount } from 'svelte';

  let userInput = $state("");
  let messages = $state([
    { type: 'agent', text: "Hello. I am the Silicon Architect. I've analyzed your 1TB CXL Switch. The 3nm PDN is holding steady at 0.42% droop. How shall we proceed with the SerDes reach?" }
  ]);

  function handleKeydown(e) {
    if (e.key === 'Enter' && userInput.trim()) {
      messages = [...messages, { type: 'user', text: userInput }];
      userInput = "";
      
      // Agent "Reasoning" simulation
      setTimeout(() => {
        messages = [...messages, { type: 'agent', text: "Analyzing your instruction against the v4.0 Sign-off Checklist. I am adjusting the twinax flyover routing to optimize for 224G reach." }];
      }, 1000);
    }
  }
</script>

<div class="app-container">
  <!-- THE SILICON VIEWPORT (80% WIDTH) -->
  <section class="viewport-section">
    <div class="meshi-logo">
      <div class="logo-circle"></div>
      <div class="logo-text">MESHI.IC</div>
    </div>
    
    <ICViewport />

    <!-- OVERLAY STATUS (Minimalist) -->
    <div style="position: absolute; bottom: 24px; left: 24px; color: var(--text-secondary); font-size: 0.75rem; letter-spacing: 0.1rem; text-transform: uppercase;">
      Status: 🟢 ARCHITECTURE FROZEN | TSMC 3nm GAA
    </div>
  </section>

  <!-- THE AUTONOMOUS ARCHITECT CHAT (20% WIDTH) -->
  <section class="chat-section">
    <div class="chat-header">
      <h2>ARCHITECT</h2>
    </div>

    <div class="chat-messages">
      {#each messages as msg}
        <div class="message {msg.type}">
          {msg.text}
        </div>
      {each}
    </div>

    <div class="chat-input">
      <input 
        type="text" 
        placeholder="Type a command for the architect..." 
        bind:value={userInput}
        onkeydown={handleKeydown}
      />
    </div>
  </section>
</div>