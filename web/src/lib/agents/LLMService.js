import { pipeline, env } from '@xenova/transformers';

// 2026 Strategy: Enable WebGPU for local acceleration
env.allowLocalModels = false;
env.useBrowserCache = true;

export class LLMService {
  constructor() {
    this.generator = null;
    this.modelName = 'Xenova/phi-1_5'; // Using a smaller version for stability; can be upgraded to Phi-3.5
    this.progress = 0;
  }

  async init(onProgress) {
    console.log("🧠 [LLM] Initializing Local Physics-Aware Brain...");
    try {
      this.generator = await pipeline('text-generation', this.modelName, {
        progress_callback: (p) => {
          this.progress = p.progress || 0;
          if (onProgress) onProgress(this.progress);
        }
      });
      console.log("✅ [LLM] Local Brain Online.");
      return true;
    } catch (err) {
      console.error("❌ [LLM] Failed to load local model:", err);
      return false;
    }
  }

  async generate(prompt, context = "") {
    if (!this.generator) return null;

    // We wrap the prompt in the Silicon Architect's personality
    const systemPrompt = `You are the 3DIC Silicon Architect. Expert in 3nm GAA, 224G SerDes, and CXL 3.1. 
    Context: ${context}
    User Request: ${prompt}
    Architect Response:`;

    const output = await this.generator(systemPrompt, {
      max_new_tokens: 128,
      temperature: 0.7,
      repetition_penalty: 1.2
    });

    return output[0].generated_text.split('Architect Response:')[1]?.trim();
  }
}
