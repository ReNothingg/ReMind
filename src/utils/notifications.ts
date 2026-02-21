import { showToast } from './toast';

export async function requestNotificationPermission() {
    if (typeof window === 'undefined') return 'unsupported';
    if (!('Notification' in window)) return 'unsupported';

    try {
        if (Notification.permission === 'granted') return 'granted';
        if (Notification.permission === 'denied') return 'denied';
        return await Notification.requestPermission();
    } catch (e) {
        return Notification.permission || 'default';
    }
}

export function notifyThinkingDone() {
    showToast('ReMind закончил размышлять.', { type: 'success' });

    if (typeof window === 'undefined') return;
    if (!('Notification' in window)) return;
    if (Notification.permission !== 'granted') return;

    try {
        new Notification('ReMind', { body: 'Закончил размышлять.' });
    } catch {
    }
}

