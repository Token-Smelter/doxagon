export function documentKeys(
    target: Window,
    navigate: (action: 'next' | 'previous' | 'first' | 'last') => void,
): () => void {
    const listener = (event: KeyboardEvent) => {
        if (event.defaultPrevented || event.metaKey || event.ctrlKey || event.altKey) return;
        const node = event.target as HTMLElement | null;
        if (node?.isContentEditable || node?.closest('input, textarea, select, button, a, summary, [role="dialog"], [data-document-keyboard="ignore"]')) return;
        let action: 'next' | 'previous' | 'first' | 'last' | undefined;
        if (['ArrowRight', 'ArrowDown', 'PageDown', ' '].includes(event.key)) action = event.shiftKey ? 'previous' : 'next';
        else if (['ArrowLeft', 'ArrowUp', 'PageUp'].includes(event.key)) action = 'previous';
        else if (event.key === 'Home') action = 'first';
        else if (event.key === 'End') action = 'last';
        if (action) {
            event.preventDefault();
            navigate(action);
        }
    };
    target.addEventListener('keydown', listener);
    return () => target.removeEventListener('keydown', listener);
}
