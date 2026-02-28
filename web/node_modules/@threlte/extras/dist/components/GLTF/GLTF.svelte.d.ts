import type { ThrelteGltf } from '../../types/types.js';
import type { GltfProps } from './types.js';
type Props = GltfProps & {
    gltf?: ThrelteGltf | undefined;
} & ThrelteGltf['materials'];
declare const Gltf: import("svelte").Component<Props, {}, "gltf" | "userData" | "scene" | "animations" | "materials" | "asset" | "cameras" | "scenes" | "parser" | "nodes">;
type Gltf = ReturnType<typeof Gltf>;
export default Gltf;
