import type { BaseProps, MaybeInstance } from '../types.js';
export declare const useAttach: <T extends MaybeInstance<any>>(getRef: () => T, getAttach: () => BaseProps<T>["attach"]) => void;
