type ToastType = 'info' | 'success' | 'warning' | 'error';

type ToastOptions = {
    durationMs?: number;
    type?: ToastType;
};

let toastContainer: HTMLDivElement | null = null;

function getToastContainer(): HTMLDivElement {
    if (toastContainer && document.body.contains(toastContainer)) return toastContainer;
    const existingContainer = document.querySelector<HTMLDivElement>('.toast-container');
    if (existingContainer) {
        toastContainer = existingContainer;
        return existingContainer;
    }

    toastContainer = document.createElement('div');
    toastContainer.className = 'toast-container';
    document.body.appendChild(toastContainer);
    return toastContainer;
}

export function showToast(
    message: string,
    { type = 'info', durationMs = 3200 }: ToastOptions = {}
): void {
    if (typeof window === 'undefined' || typeof document === 'undefined') return;
    if (!message) return;

    const container = getToastContainer();
    const el = document.createElement('div');
    el.className = ['toast-message', type].filter(Boolean).join(' ');
    el.textContent = message;
    container.appendChild(el);

    const exitMs = 280;
    window.setTimeout(() => {
        el.classList.add('exiting');
        window.setTimeout(() => {
            el.remove();
        }, exitMs);
    }, Math.max(0, durationMs));
}

