import React, { act, useEffect } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { apiService } from '../services/api';
import { useAudio } from './useAudio';

class FakeAudio {
    static instances: FakeAudio[] = [];

    currentTime = 0;
    duration = 2;
    readyState = 1;
    onended: (() => void) | null = null;
    onerror: (() => void) | null = null;
    onloadedmetadata: (() => void) | null = null;
    ontimeupdate: (() => void) | null = null;
    readonly src: string;
    pause = vi.fn();
    play = vi.fn().mockResolvedValue(undefined);

    constructor(src: string) {
        this.src = src;
        FakeAudio.instances.push(this);
    }
}

describe('useAudio', () => {
    let container: HTMLDivElement;
    let root: Root;
    let latest: ReturnType<typeof useAudio>;

    beforeEach(() => {
        FakeAudio.instances = [];
        vi.stubGlobal('Audio', FakeAudio);
        container = document.createElement('div');
        document.body.appendChild(container);
        root = createRoot(container);

        function Harness() {
            const value = useAudio('message-1');
            useEffect(() => {
                latest = value;
            }, [value]);
            return null;
        }

        act(() => root.render(React.createElement(Harness)));
    });

    afterEach(() => {
        act(() => root.unmount());
        container.remove();
        vi.unstubAllGlobals();
    });

    it('waits for metadata, plays every segment, and updates the overall progress', async () => {
        vi.spyOn(apiService, 'synthesize').mockResolvedValue({
            ok: true,
            segments: [
                { audio_base64: 'segment-one' },
                { audio_base64: 'segment-two' },
            ],
        });

        await act(async () => {
            await latest.speak('Test speech');
        });

        expect(latest.isLoading).toBe(false);
        expect(latest.isReady).toBe(true);
        expect(latest.totalDuration).toBe(4);
        expect(FakeAudio.instances[0].src).toMatch(/^data:audio\/mpeg;base64,/);
        expect(FakeAudio.instances[0].play).toHaveBeenCalledOnce();

        await act(async () => {
            FakeAudio.instances[0].onended?.();
            await new Promise((resolve) => setTimeout(resolve, 0));
        });

        expect(FakeAudio.instances[1].play).toHaveBeenCalledOnce();

        act(() => {
            FakeAudio.instances[1].currentTime = 0.75;
            FakeAudio.instances[1].ontimeupdate?.();
        });

        expect(latest.currentTime).toBe(2.75);
    });
});
