import { type InteractivityOptions } from './context.js';
declare const interactivity: (options?: InteractivityOptions) => import("./context.js").InteractivityContext;
export { useInteractivity } from './context.js';
export type { DomEvent, Intersection, IntersectionEvent, ThrelteEvents as EventMap, InteractivityProps } from './types.js';
export { interactivity };
