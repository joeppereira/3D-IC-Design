import type { CubeCameraProps } from './types.js';
declare const CubeCamera: import("svelte").Component<CubeCameraProps, {
    camera: import("three").CubeCamera;
    renderTarget: import("three").WebGLCubeRenderTarget;
    update: () => void;
    restart: () => void;
}, "ref">;
type CubeCamera = ReturnType<typeof CubeCamera>;
export default CubeCamera;
