import type { AnimatedSpriteProps } from './types.js';
declare const AnimatedSpriteMaterial: import("svelte").Component<AnimatedSpriteProps, {
    /**
       * Plays the animation.
       */ play: () => Promise<void>;
    /**
       * Pauses the animation.
       */ pause: () => void;
}, "ref">;
type AnimatedSpriteMaterial = ReturnType<typeof AnimatedSpriteMaterial>;
export default AnimatedSpriteMaterial;
