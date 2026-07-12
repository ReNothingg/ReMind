import { useState, useRef, useCallback, useEffect } from 'react';
import { apiService } from '../services/api';

type AudioSegmentPayload = {
    audio_base64: string;
    original_text?: string;
};

const isAudioSegmentPayload = (value: unknown): value is AudioSegmentPayload => (
    typeof value === 'object' &&
    value !== null &&
    typeof (value as { audio_base64?: unknown }).audio_base64 === 'string' &&
    (value as { audio_base64: string }).audio_base64.length > 0
);

const getSynthesizeError = (data: unknown) => {
    if (typeof data === 'object' && data !== null && typeof (data as { error?: unknown }).error === 'string') {
        return (data as { error: string }).error;
    }

    return 'Нет валидных аудио сегментов.';
};

const estimateSpeechDuration = (segment: AudioSegmentPayload) => {
    const text = typeof segment.original_text === 'string' ? segment.original_text.trim() : '';
    const wordCount = text ? text.split(/\s+/u).filter(Boolean).length : 0;
    const estimatedSeconds = wordCount > 0 ? wordCount / 2.4 : Math.max(text.length / 14, 1);
    return Math.min(Math.max(estimatedSeconds, 1), 300);
};

export const useAudio = (_messageId) => {
    const [isPlaying, setIsPlaying] = useState(false);
    const [isLoading, setIsLoading] = useState(false);
    const [isError, setIsError] = useState(false);
    const [isVisible, setIsVisible] = useState(false);
    const [currentTime, setCurrentTime] = useState(0);
    const [totalDuration, setTotalDuration] = useState(0);
    const [waveformPoints, setWaveformPoints] = useState(null);
    const audioSegmentsRef = useRef([]);
    const currentSegmentIndexRef = useRef(0);
    const durationsRef = useRef([]);
    const updateIntervalRef = useRef(null);
    const isPlayingRef = useRef(false);
    const isVisibleRef = useRef(false);
    const isErrorRef = useRef(false);
    const isLoadingRef = useRef(false);
    const requestIdRef = useRef(0);

    const generateWaveformPoints = useCallback((text) => {
        const numPoints = 100;
        const points = [];
        let seed = (text || "s").split('').reduce((acc, char) => (acc * 31 + char.charCodeAt(0)) & 0xFFFFFFFF, 0);
        const rand = () => { seed = Math.sin(seed) * 10000; return seed - Math.floor(seed); };
        const [baseFreq, baseAmp, detailFreq, detailAmp, slowFreq, slowAmp] = [
            2 + rand() * 4, 0.3 + rand() * 0.2, 15 + rand() * 10, 0.05 + rand() * 0.1, 0.5 + rand() * 1, 0.1 + rand() * 0.15
        ];
        for (let i = 0; i < numPoints; i++) {
            const x = i / (numPoints - 1);
            const y = (Math.sin(x * Math.PI * 2 * baseFreq) * baseAmp + Math.sin(x * Math.PI * 2 * detailFreq) * detailAmp + Math.sin(x * Math.PI * 2 * slowFreq) * slowAmp) * Math.sin(x * Math.PI);
            points.push(Math.max(0.05, 0.5 + y * 0.4));
        }
        return points;
    }, []);

    const calculateDurations = useCallback(async (segments, fallbackDurations) => {
        const metadataPromises = segments.map((audio, index) => new Promise(resolve => {
            if (audio.readyState >= 1 && isFinite(audio.duration)) return resolve(audio.duration);
            const fallback = fallbackDurations[index] || 1;
            const timeoutId = setTimeout(() => resolve(fallback), 1500);
            audio.onloadedmetadata = () => { clearTimeout(timeoutId); resolve(isFinite(audio.duration) && audio.duration > 0 ? audio.duration : fallback); };
            audio.onerror = () => { clearTimeout(timeoutId); resolve(fallback); };
        }));
        const segmentDurations = await Promise.all(metadataPromises);
        durationsRef.current = segmentDurations;
        const total = segmentDurations.reduce((acc, d) => acc + d, 0);
        setTotalDuration(total);
        return total;
    }, []);

    const updatePlayerUI = useCallback(() => {
        if (!isVisibleRef.current) return;
        let currentTimeOverall = durationsRef.current.slice(0, currentSegmentIndexRef.current).reduce((acc, d) => acc + d, 0);
        const currentAudio = audioSegmentsRef.current[currentSegmentIndexRef.current];
        if (currentAudio) {
            currentTimeOverall += currentAudio.currentTime || 0;
        }
        setCurrentTime(currentTimeOverall);
    }, []);

    const clearUpdateInterval = useCallback(() => {
        if (updateIntervalRef.current) {
            clearInterval(updateIntervalRef.current);
            updateIntervalRef.current = null;
        }
    }, []);

    const pauseAudio = useCallback((fullStop = false) => {
        isPlayingRef.current = false;
        setIsPlaying(false);
        audioSegmentsRef.current[currentSegmentIndexRef.current]?.pause();
        if (fullStop) {
            audioSegmentsRef.current.forEach(audio => {
                audio.pause();
                audio.currentTime = 0;
            });
            currentSegmentIndexRef.current = 0;
            setCurrentTime(0);
        }
    }, []);

    const handlePlaybackEnd = useCallback(() => {
        clearUpdateInterval();
        pauseAudio(true);
    }, [clearUpdateInterval, pauseAudio]);

    const playAudio = useCallback(() => {
        if (isErrorRef.current || currentSegmentIndexRef.current >= audioSegmentsRef.current.length) {
            handlePlaybackEnd();
            return;
        }
        isPlayingRef.current = true;
        setIsPlaying(true);
        const audio = audioSegmentsRef.current[currentSegmentIndexRef.current];
        if (audio) {
            audio.play().catch(error => {
                if (error.name !== 'AbortError' && !error.message.includes('interrupted')) {
                    clearUpdateInterval();
                    pauseAudio();
                    setIsError(true);
                    isErrorRef.current = true;
                    isPlayingRef.current = false;
                    setIsPlaying(false);
                }
            });
        }
    }, [clearUpdateInterval, handlePlaybackEnd, pauseAudio]);

    const seekAudio = useCallback((targetTime) => {
        const duration = durationsRef.current.reduce((acc, value) => acc + value, 0);
        if (!Number.isFinite(targetTime) || duration <= 0) return;
        const clampedTarget = Math.min(Math.max(targetTime, 0), duration);
        const wasPlaying = isPlayingRef.current;
        if (wasPlaying) pauseAudio();
        let accumulatedTime = 0;
        let newSegmentIndex = durationsRef.current.findIndex((duration) => {
            if (clampedTarget <= accumulatedTime + duration) return true;
            accumulatedTime += duration;
            return false;
        });
        if (newSegmentIndex === -1) newSegmentIndex = 0;
        currentSegmentIndexRef.current = newSegmentIndex;
        const timeInTargetSegment = Math.max(0, clampedTarget - accumulatedTime);
        audioSegmentsRef.current.forEach((audio, index) => {
            audio.currentTime = (index === newSegmentIndex) ? timeInTargetSegment : 0;
        });
        setCurrentTime(clampedTarget);
        if (wasPlaying) playAudio();
    }, [pauseAudio, playAudio]);

    const speak = useCallback(async (text) => {
        if (isLoadingRef.current) return;
        if (isVisibleRef.current && isErrorRef.current) {
            isVisibleRef.current = false;
            setIsVisible(false);
        }
        if (isVisibleRef.current && isPlayingRef.current) {
            requestIdRef.current += 1;
            isVisibleRef.current = false;
            setIsVisible(false);
            pauseAudio(true);
            return;
        }
        if (isVisibleRef.current) {
            playAudio();
            return;
        }

        const requestId = requestIdRef.current + 1;
        requestIdRef.current = requestId;
        clearUpdateInterval();
        audioSegmentsRef.current.forEach((audio) => {
            audio.pause();
            audio.currentTime = 0;
        });
        audioSegmentsRef.current = [];
        durationsRef.current = [];
        setCurrentTime(0);
        setTotalDuration(0);
        setWaveformPoints(null);
        isLoadingRef.current = true;
        setIsLoading(true);
        isErrorRef.current = false;
        setIsError(false);
        isVisibleRef.current = true;
        setIsVisible(true);
        currentSegmentIndexRef.current = 0;

        try {
            const data = await apiService.synthesize(text);
            if (requestId !== requestIdRef.current) return;
            const validSegments = Array.isArray(data?.segments)
                ? data.segments.filter(isAudioSegmentPayload)
                : [];

            if (validSegments.length === 0) {
                throw new Error(getSynthesizeError(data));
            }

            const segments = validSegments.map((segment) => (
                new Audio(`data:audio/mpeg;base64,${segment.audio_base64}`)
            ));

            if (segments.length === 0) {
                throw new Error('Нет валидных аудио сегментов после обработки.');
            }

            audioSegmentsRef.current = segments;
            const points = generateWaveformPoints(text);
            setWaveformPoints(points);

            await calculateDurations(
                segments,
                validSegments.map(estimateSpeechDuration)
            );
            if (requestId !== requestIdRef.current) return;

            segments.forEach((audio, index) => {
                audio.ondurationchange = () => {
                    if (!Number.isFinite(audio.duration) || audio.duration <= 0) return;
                    durationsRef.current[index] = audio.duration;
                    setTotalDuration(durationsRef.current.reduce((acc, value) => acc + value, 0));
                };
                audio.onended = () => {
                    if (isPlayingRef.current && index < segments.length - 1) {
                        currentSegmentIndexRef.current = index + 1;
                        setTimeout(() => playAudio(), 0);
                    } else {
                        handlePlaybackEnd();
                    }
                };
                audio.onerror = () => {
                    clearUpdateInterval();
                    pauseAudio();
                    isErrorRef.current = true;
                    isPlayingRef.current = false;
                    setIsError(true);
                    setIsPlaying(false);
                };
                audio.ontimeupdate = () => {
                    if (isPlayingRef.current && currentSegmentIndexRef.current === index) {
                        updatePlayerUI();
                    }
                };
            });

            isLoadingRef.current = false;
            setIsLoading(false);
            clearUpdateInterval();
            updateIntervalRef.current = setInterval(updatePlayerUI, 100);
            playAudio();
        } catch (error) {
            if (requestId !== requestIdRef.current) return;
            console.error("Speech error", error);
            clearUpdateInterval();
            isErrorRef.current = true;
            isLoadingRef.current = false;
            isPlayingRef.current = false;
            setIsError(true);
            setIsLoading(false);
            setIsPlaying(false);
        }
    }, [pauseAudio, playAudio, generateWaveformPoints, calculateDurations, clearUpdateInterval, handlePlaybackEnd, updatePlayerUI]);

    const stop = useCallback(() => {
        requestIdRef.current += 1;
        clearUpdateInterval();
        pauseAudio(true);
        isLoadingRef.current = false;
        isVisibleRef.current = false;
        setIsLoading(false);
        setIsVisible(false);
    }, [clearUpdateInterval, pauseAudio]);

    useEffect(() => () => {
        requestIdRef.current += 1;
        clearUpdateInterval();
        audioSegmentsRef.current.forEach((audio) => {
            audio.pause();
            audio.currentTime = 0;
        });
    }, [clearUpdateInterval]);

    const formatTime = useCallback((seconds) => {
        const safeSeconds = Number.isFinite(seconds) && seconds > 0 ? seconds : 0;
        const mins = Math.floor(safeSeconds / 60);
        const secs = Math.floor(safeSeconds % 60);
        return `${mins}:${secs.toString().padStart(2, '0')}`;
    }, []);

    return {
        speak,
        stop,
        isPlaying,
        isLoading,
        isError,
        isVisible,
        currentTime,
        totalDuration,
        isReady: totalDuration > 0 && audioSegmentsRef.current.length > 0,
        formatTime,
        seekAudio,
        waveformPoints,
        togglePlayback: () => isPlaying ? pauseAudio() : playAudio()
    };
};
