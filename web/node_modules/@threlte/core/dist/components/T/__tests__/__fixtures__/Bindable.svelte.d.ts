import type { Group } from 'three';
interface Props {
    is: Group;
    onRefCreate: (ref: Group | undefined) => void;
}
declare const Bindable: import("svelte").Component<Props, {}, "">;
type Bindable = ReturnType<typeof Bindable>;
export default Bindable;
