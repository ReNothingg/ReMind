let toastContainer = null;

function getToastContainer() {
    if (toastContainer && document.body.contains(toastContainer)) return toastContainer;
    toastContainer = document.querySelector('.toast-container');
    if (toastContainer) return toastContainer;

    toastContainer = document.createElement('div');
    toastContainer.className = 'toast-container';
    document.body.appendChild(toastContainer);
    return toastContainer;
}

export function showToast(message, { type = 'info', durationMs = 3200 } = {}) {
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

