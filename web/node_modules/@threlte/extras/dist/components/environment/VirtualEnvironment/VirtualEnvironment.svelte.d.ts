import type { VirtualEnvironmentProps } from './types.js';
declare const VirtualEnvironment: import("svelte").Component<VirtualEnvironmentProps, {
    camera: import("three").CubeCamera;
    renderTarget: import("three").WebGLCubeRenderTarget;
    update: () => void;
    restart: () => void;
}, "">;
type VirtualEnvironment = ReturnType<typeof VirtualEnvironment>;
export default VirtualEnvironment;
