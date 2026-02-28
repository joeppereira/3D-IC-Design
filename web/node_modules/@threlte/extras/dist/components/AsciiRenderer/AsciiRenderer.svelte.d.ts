import type { AsciiRendererProps } from './types.js';
import { AsciiEffect } from 'three/examples/jsm/effects/AsciiEffect.js';
declare const AsciiRenderer: import("svelte").Component<AsciiRendererProps, {
    getEffect: () => AsciiEffect;
    start: () => void;
    stop: () => void;
}, "">;
type AsciiRenderer = ReturnType<typeof AsciiRenderer>;
export default AsciiRenderer;
