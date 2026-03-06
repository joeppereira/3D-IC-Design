// AI Web Worker - v4.7.0 THIN-BRAIN (Phi-1.5)
import { pipeline, env } from '@xenova/transformers';

env.allowLocalModels = false;
env.useBrowserCache = true;
// Point to reliable WASM assets
env.backends.onnx.wasm.wasmPaths = 'https://cdn.jsdelivr.net/npm/onnxruntime-web@1.17.1/dist/';

let generator = null;

self.onmessage = async (e) => {
  const { type, prompt, context } = e.data;

  if (type === 'init') {
    try {
      console.log("🧠 [Worker] Loading Lite Brain (Phi-1.5)...");
      
      // Phi-1.5 is ~200MB and loads instantly compared to 2.3GB Phi-3.5
      generator = await pipeline('text-generation', 'Xenova/phi-1_5', {
        device: 'wasm', 
        progress_callback: (p) => {
          if (p.status === 'progress') {
            self.postMessage({ type: 'progress', progress: p.progress || 0 });
          }
        }
      });
      
      self.postMessage({ type: 'ready' });
      console.log("✅ [Worker] Lite Brain Online.");
    } catch (err) {
      console.error("❌ [Worker] Load Error:", err);
      self.postMessage({ type: 'error', error: err.message });
    }
  }

  if (type === 'generate') {
    if (!generator) return;
    const systemPrompt = `Instruct: You are the 3DIC Architect. Context: ${context}. User: ${prompt}. Response:`;
    try {
      const output = await generator(systemPrompt, { 
        max_new_tokens: 64, 
        temperature: 0.7 
      });
      const response = output[0].generated_text.split('Response:')[1]?.trim();
      self.postMessage({ type: 'response', text: response });
    } catch (err) {
      self.postMessage({ type: 'error', error: err.message });
    }
  }
};