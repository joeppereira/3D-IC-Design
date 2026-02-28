interface Props {
    plugin?: {
        fn: (args: any) => void;
        props?: string[];
    };
    attached?: boolean;
    dispose?: boolean;
}
declare const Scene: import("svelte").Component<Props, {}, "">;
type Scene = ReturnType<typeof Scene>;
export default Scene;
