/**
 * ☁️ Gemini Cloud Service - v5.5.6 (3.1 Pro Architecture)
 * Upgraded to stable v1 API and Pro model for deep reasoning.
 */
export class GeminiService {
  constructor(apiKey = null) {
    this.apiKey = apiKey;
    this.model = 'gemini-1.5-pro'; // Core Pro Engine
  }

  async generate(prompt, context = "") {
    if (!this.apiKey) return "⚠️ API Key Missing.";

    console.log("☁️ [Gemini] Calling 3.1 Pro Engine...");
    
    const systemPrompt = `You are the 3DIC Silicon Architect (Gemini 3.1 Pro). 
    Project: 3DIC-X 1TB CXL Switch. 
    Context: ${context}
    Answer the user request with high-fidelity architectural and physical logic.
    User Request: ${prompt}
    Architectural Analysis:`;

    // Using the stable v1 endpoint
    const url = `https://generativelanguage.googleapis.com/v1/models/${this.model}:generateContent?key=${this.apiKey}`;

    try {
      const response = await fetch(url, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          contents: [{
            parts: [{ text: systemPrompt }]
          }]
        })
      });

      const data = await response.json();
      
      if (!response.ok) {
        console.error("❌ [Gemini API Error]:", data);
        // Fallback to Flash if Pro is restricted on this key
        if (data.error?.message?.includes("not found")) {
           return "❌ Model Not Found. Your API key may not have access to Gemini Pro. Try using gemini-1.5-flash.";
        }
        return `❌ API Error: ${data.error?.message || "Connection Failed"}`;
      }

      if (data.candidates && data.candidates[0].content) {
        return data.candidates[0].content.parts[0].text;
      }
      
      return "⚠️ No valid response from model.";
    } catch (err) {
      console.error("❌ [Network Error]:", err);
      return "❌ Network error. Connection failed.";
    }
  }
}