import { mount } from 'svelte';
import App from './App.svelte';

console.log("🔥 [3DIC] Main.js cache-busted execution.");

// Clear any existing service workers if they exist
if ('serviceWorker' in navigator) {
  navigator.serviceWorker.getRegistrations().then(registrations => {
    for (let registration of registrations) {
      registration.unregister();
      console.log("🧹 [3DIC] Service Worker Unregistered.");
    }
  });
}

const app = mount(App, {
  target: document.getElementById('app'),
});

export default app;
