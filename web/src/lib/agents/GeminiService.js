/**
 * ☁️ Gemini Cloud Service (2026 Integration)
 * Handles high-level architectural strategy calls to Gemini 1.5/2.0 Pro
 */
export class GeminiService {
  constructor(apiKey = null) {
    this.apiKey = apiKey;
    this.model = 'gemini-1.5-pro'; // Defaulting to 1.5 Pro for architectural depth
  }

  async generate(prompt, context = "") {
    if (!this.apiKey) {
      return "⚠️ [Cloud Error] No Gemini API Key detected. Please provide a key in the 'Settings' panel or ask me to 'use local phi'.";
    }

    console.log("☁️ [3DIC] Invoking Gemini Cloud Brain...");
    
    const systemPrompt = `You are the 3DIC Lead Architect (Gemini Cloud Brain). 
    Project: Search King (1TB CXL Switch, 3nm GAA).
    Constraint: High-fidelity engineering only.
    Context: ${context}
    User Request: ${prompt}
    Architectural Decision:`;

    try {
      // 2026 Browser Fetch pattern for Gemini API
      const response = await fetch(`https://generativelanguage.googleapis.com/v1beta/models/${this.model}:generateContent?key=${this.apiKey}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          contents: [{ parts: [{ text: systemPrompt }] }]
        })
      });

      const data = await response.json();
      return data.candidates[0].content.parts[0].text;
    } catch (err) {
      console.error("❌ [Cloud] Gemini API Call Failed:", err);
      return "❌ [Cloud Error] Failed to reach Gemini. Check your network or API key.";
    }
  }
}
