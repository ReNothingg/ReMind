import { useState, useRef, useCallback } from 'react';
import { apiService } from '../services/api';

export const useAudio = (messageId) => {
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
    const playerContainerRef = useRef(null);

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

    const calculateDurations = useCallback(async (segments) => {
        const metadataPromises = segments.map((audio, index) => new Promise(resolve => {
            if (audio.readyState >= 1 && isFinite(audio.duration)) return resolve(audio.duration);
            const timeoutId = setTimeout(() => resolve(0), 5000);
            audio.onloadedmetadata = () => { clearTimeout(timeoutId); resolve(isFinite(audio.duration) ? audio.duration : 0); };
            audio.onerror = () => { clearTimeout(timeoutId); resolve(0); };
        }));
        const segmentDurations = await Promise.all(metadataPromises);
        durationsRef.current = segmentDurations;
        const total = segmentDurations.reduce((acc, d) => acc + d, 0);
        setTotalDuration(total);
        return total;
    }, []);

    const updatePlayerUI = useCallback(() => {
        if (!isVisible) return;
        let currentTimeOverall = durationsRef.current.slice(0, currentSegmentIndexRef.current).reduce((acc, d) => acc + d, 0);
        const currentAudio = audioSegmentsRef.current[currentSegmentIndexRef.current];
        if (currentAudio) {
            currentTimeOverall += currentAudio.currentTime || 0;
        }
        setCurrentTime(currentTimeOverall);
    }, [isVisible]);

    const playAudio = useCallback(() => {
        if (isError || currentSegmentIndexRef.current >= audioSegmentsRef.current.length) {
            handlePlaybackEnd();
            return;
        }
        setIsPlaying(true);
        const audio = audioSegmentsRef.current[currentSegmentIndexRef.current];
        if (audio) {
            audio.play().catch(error => {
                if (error.name !== 'AbortError' && !error.message.includes('interrupted')) {
                    setIsError(true);
                    setIsPlaying(false);
                }
            });
        }
    }, [isError]);

    const pauseAudio = useCallback((fullStop = false) => {
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
        pauseAudio(true);
        setIsVisible(false);
    }, [pauseAudio]);

    const seekAudio = useCallback((targetTime) => {
        const wasPlaying = isPlaying;
        if (wasPlaying) pauseAudio();
        let accumulatedTime = 0;
        let newSegmentIndex = durationsRef.current.findIndex((duration, i) => {
            if (targetTime <= accumulatedTime + duration) return true;
            accumulatedTime += duration;
            return false;
        });
        if (newSegmentIndex === -1) newSegmentIndex = 0;
        currentSegmentIndexRef.current = newSegmentIndex;
        const timeInTargetSegment = targetTime - accumulatedTime;
        audioSegmentsRef.current.forEach((audio, i) => {
            audio.currentTime = (i === newSegmentIndex) ? timeInTargetSegment : 0;
        });
        setCurrentTime(targetTime);
        if (wasPlaying) playAudio();
    }, [isPlaying, pauseAudio, playAudio]);

    const speak = useCallback(async (text) => {
        if (isVisible && isPlaying) {
            setIsVisible(false);
            pauseAudio(true);
            return;
        }
        if (isVisible) {
            playAudio();
            return;
        }

        setIsLoading(true);
        setIsError(false);
        setIsVisible(true);
        currentSegmentIndexRef.current = 0;

        try {
            const data = await apiService.synthesize(text);
            setIsLoading(false);

            if (!data?.segments?.some(s => s.audio_base64)) {
                throw new Error(data?.error || 'Нет валидных аудио сегментов.');
            }

            const segments = data.segments
                .filter(s => s.audio_base64)
                .map(s => new Audio(`data:audio/mp3;base64,${s.audio_base64}`));

            if (segments.length === 0) {
                throw new Error('Нет валидных аудио сегментов после обработки.');
            }

            audioSegmentsRef.current = segments;
            const points = generateWaveformPoints(text);
            setWaveformPoints(points);

            await calculateDurations(segments);

            segments.forEach((audio, index) => {
                audio.onended = () => {
                    if (isPlaying && index < segments.length - 1) {
                        currentSegmentIndexRef.current = index + 1;
                        setTimeout(() => playAudio(), 0);
                    } else {
                        handlePlaybackEnd();
                    }
                };
                audio.onerror = () => {
                    setIsError(true);
                    setIsPlaying(false);
                };
                audio.ontimeupdate = () => {
                    if (isPlaying && currentSegmentIndexRef.current === index) {
                        updatePlayerUI();
                    }
                };
            });

            updateIntervalRef.current = setInterval(updatePlayerUI, 100);
            playAudio();
        } catch (error) {
            console.error("Speech error", error);
            setIsError(true);
            setIsLoading(false);
            setIsPlaying(false);
        }
    }, [isVisible, isPlaying, pauseAudio, playAudio, generateWaveformPoints, calculateDurations, handlePlaybackEnd, updatePlayerUI]);

    const stop = useCallback(() => {
        if (updateIntervalRef.current) {
            clearInterval(updateIntervalRef.current);
            updateIntervalRef.current = null;
        }
        pauseAudio(true);
        setIsVisible(false);
    }, [pauseAudio]);

    const formatTime = useCallback((seconds) => {
        const mins = Math.floor(seconds / 60);
        const secs = Math.floor(seconds % 60);
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
        formatTime,
        seekAudio,
        waveformPoints,
        togglePlayback: () => isPlaying ? pauseAudio() : playAudio()
    };
};