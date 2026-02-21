import React, { useState, useEffect, useRef } from 'react';
const INSTRUMENT_MAP = {
    kick: { name: 'Бас-барабан', icon: 'kick' },
    snare: { name: 'Малый барабан', icon: 'snare' },
    clap: { name: 'Хлопок', icon: 'clap' },
    hihat: { name: 'Хай-хэт', icon: 'hihat' },
    open_hat: { name: 'Открытый хэт', icon: 'ride' },
    tom: { name: 'Том', icon: 'tom' },
    triangle: { name: 'Треугольник', icon: 'triangle' },
    cowbell: { name: 'Ковбел', icon: 'cowbell' }
};

const DRUM_TYPES = Object.keys(INSTRUMENT_MAP);

const Beatbox = ({ initialState }) => {
    const containerRef = useRef(null);
    const audioContextRef = useRef(null);
    const masterGainRef = useRef(null);
    const schedulerTimerRef = useRef(null);
    const nextNoteTimeRef = useRef(0);
    const tracksRef = useRef([]);
    const metaRef = useRef({ bpm: 120, bars: 4 });
    const isPlayingRef = useRef(false);
    const currentStepRef = useRef(0);
    const [meta, setMeta] = useState(initialState?.meta || { bpm: 120, bars: 4 });
    const [tracks, setTracks] = useState(initialState?.tracks || [
        { id: "d_kick", type: "drum", drum: "kick", steps: Array(64).fill(0).map((_, i) => i % 4 === 0 ? 1 : 0), adsr: { attack: 0.001, decay: 0.12, sustain: 0.001, release: 0.08 } },
        { id: "d_snare", type: "drum", drum: "snare", steps: Array(64).fill(0).map((_, i) => (i + 4) % 8 === 0 ? 1 : 0), adsr: { attack: 0.001, decay: 0.12, sustain: 0.001, release: 0.12 } },
        { id: "d_hihat", type: "drum", drum: "hihat", steps: Array(64).fill(0).map((_, i) => i % 2 === 0 ? 1 : 0), adsr: { attack: 0.001, decay: 0.05, sustain: 0.001, release: 0.02 } }
    ]);
    const [isPlaying, setIsPlaying] = useState(false);
    const [visualStep, setVisualStep] = useState(0);
    const [instrumentPanel, setInstrumentPanel] = useState({
        isOpen: false,
        trackIndex: null,
        top: 0,
        left: 0
    });

    const [openAdsrPanel, setOpenAdsrPanel] = useState(null);
    const [draggedTrackIndex, setDraggedTrackIndex] = useState(null);
    const [dragOverIndex, setDragOverIndex] = useState(null);
    useEffect(() => { tracksRef.current = tracks; }, [tracks]);
    useEffect(() => { metaRef.current = meta; }, [meta]);
    useEffect(() => { isPlayingRef.current = isPlaying; }, [isPlaying]);
    useEffect(() => {
        const AudioCtx = window.AudioContext || window.webkitAudioContext;
        const ctx = new AudioCtx();
        const gain = ctx.createGain();
        gain.gain.value = 0.9;
        gain.connect(ctx.destination);

        audioContextRef.current = ctx;
        masterGainRef.current = gain;

        return () => {
            stopScheduler();
            if (ctx.state !== 'closed') ctx.close();
        };
    }, []);
    const _createNoiseBuffer = (duration) => {
        const ctx = audioContextRef.current;
        const length = Math.floor(duration * ctx.sampleRate);
        const buffer = ctx.createBuffer(1, length, ctx.sampleRate);
        const data = buffer.getChannelData(0);
        for (let i = 0; i < length; i++) {
            data[i] = (Math.random() * 2 - 1) * Math.pow(1 - i / length, 0.6);
        }
        return buffer;
    };

    const _applyGainEnvelope = (gainNode, time, adsr) => {
        const a = Math.max(0.001, adsr.attack || 0.001);
        const d = Math.max(0.001, adsr.decay || 0.05);
        const s = ('sustain' in adsr) ? adsr.sustain : 0.001;
        gainNode.gain.cancelScheduledValues(time);
        gainNode.gain.setValueAtTime(0.0001, time);
        gainNode.gain.exponentialRampToValueAtTime(Math.max(0.01, 1.0), time + a);
        gainNode.gain.exponentialRampToValueAtTime(Math.max(0.001, s), time + a + d);
    };

    const createDrumSoundAtTime = (type, adsr, time) => {
        const ctx = audioContextRef.current;
        const out = masterGainRef.current;
        if (!ctx || !out) return;

        if (type === 'kick') {
            const osc = ctx.createOscillator();
            osc.type = 'sine';
            const oscGain = ctx.createGain();
            oscGain.gain.value = 0.0;
            osc.connect(oscGain).connect(out);
            osc.frequency.setValueAtTime(140, time);
            osc.frequency.exponentialRampToValueAtTime(Math.max(0.1, 40), time + 0.18);
            _applyGainEnvelope(oscGain, time, adsr);
            osc.start(time);
            const stopTime = time + (adsr.attack + adsr.decay + adsr.release + 0.15);
            oscGain.gain.exponentialRampToValueAtTime(0.0001, stopTime);
            osc.stop(stopTime + 0.01);
        } else if (type === 'snare') {
            const noiseBuffer = _createNoiseBuffer(0.6);
            const noiseSrc = ctx.createBufferSource();
            noiseSrc.buffer = noiseBuffer;
            const noiseGain = ctx.createGain();
            const bp = ctx.createBiquadFilter();
            bp.type = 'bandpass';
            bp.frequency.value = 1800;
            bp.Q.value = 0.9;
            noiseSrc.connect(bp).connect(noiseGain).connect(out);
            _applyGainEnvelope(noiseGain, time, adsr);
            const bodyOsc = ctx.createOscillator();
            bodyOsc.type = 'triangle';
            bodyOsc.frequency.setValueAtTime(180, time);
            const bodyGain = ctx.createGain();
            bodyGain.gain.value = 0.0;
            bodyOsc.connect(bodyGain).connect(out);
            _applyGainEnvelope(bodyGain, time, { attack: 0.001, decay: 0.08, sustain: 0.001 });
            noiseSrc.start(time); bodyOsc.start(time);
            const stopTime = time + adsr.attack + adsr.decay + adsr.release + 0.25;
            noiseGain.gain.exponentialRampToValueAtTime(0.0001, stopTime);
            bodyGain.gain.exponentialRampToValueAtTime(0.0001, stopTime);
            noiseSrc.stop(stopTime + 0.02); bodyOsc.stop(stopTime + 0.02);
        } else if (type === 'clap') {
            const makeBurst = (delay) => {
                const nb = _createNoiseBuffer(0.12);
                const ns = ctx.createBufferSource();
                ns.buffer = nb;
                const g = ctx.createGain();
                const hp = ctx.createBiquadFilter();
                hp.type = 'highpass';
                hp.frequency.value = 900;
                ns.connect(hp).connect(g).connect(out);
                _applyGainEnvelope(g, time + delay, { attack: 0.001, decay: 0.03, sustain: 0.001 });
                ns.start(time + delay);
                const st = time + delay + 0.12;
                g.gain.exponentialRampToValueAtTime(0.0001, st);
                ns.stop(st + 0.01);
            };
            makeBurst(0.0); makeBurst(0.02); makeBurst(0.045);
        } else if (type === 'hihat' || type === 'open_hat') {
            const duration = (type === 'open_hat') ? 0.4 : 0.08;
            const buffer = _createNoiseBuffer(duration);
            const src = ctx.createBufferSource();
            src.buffer = buffer;
            const hp = ctx.createBiquadFilter();
            hp.type = 'highpass';
            hp.frequency.value = (type === 'open_hat') ? 5000 : 8000;
            const bp = ctx.createBiquadFilter();
            bp.type = 'bandpass';
            bp.frequency.value = 10000;
            bp.Q.value = (type === 'open_hat') ? 0.3 : 1.5;
            const gainNode = ctx.createGain();
            src.connect(hp).connect(bp).connect(gainNode).connect(out);
            const adsrLocal = { ...adsr };
            if (type === 'open_hat') { adsrLocal.decay = Math.max(adsr.decay, 0.18); adsrLocal.release = Math.max(adsr.release, 0.2); }
            else { adsrLocal.decay = Math.max(adsr.decay, 0.03); adsrLocal.release = Math.max(adsr.release, 0.02); }
            _applyGainEnvelope(gainNode, time, adsrLocal);
            src.start(time);
            const st = time + adsrLocal.attack + adsrLocal.decay + adsrLocal.release + duration;
            gainNode.gain.exponentialRampToValueAtTime(0.0001, st);
            src.stop(st + 0.02);
        } else if (type === 'tom') {
            const osc = ctx.createOscillator();
            osc.type = 'sine';
            osc.frequency.setValueAtTime(200, time);
            osc.frequency.exponentialRampToValueAtTime(90, time + 0.28);
            const fl = ctx.createBiquadFilter();
            fl.type = 'lowpass';
            fl.frequency.value = 1200;
            const g = ctx.createGain();
            osc.connect(fl).connect(g).connect(out);
            _applyGainEnvelope(g, time, { attack: adsr.attack, decay: 0.12, sustain: 0.001 });
            osc.start(time);
            const stopTime = time + adsr.attack + adsr.decay + adsr.release + 0.3;
            g.gain.exponentialRampToValueAtTime(0.0001, stopTime);
            osc.stop(stopTime + 0.01);
        } else if (type === 'cowbell' || type === 'triangle') {
            const o1 = ctx.createOscillator();
            const o2 = ctx.createOscillator();
            o1.type = 'square';
            o2.type = 'sine';
            const base = (type === 'cowbell') ? 1300 : 800;
            o1.frequency.setValueAtTime(base, time);
            o2.frequency.setValueAtTime(base * 1.495, time);
            const mix = ctx.createGain();
            mix.gain.value = 0.8;
            const hp = ctx.createBiquadFilter();
            hp.type = 'highpass';
            hp.frequency.value = 700;
            o1.connect(mix); o2.connect(mix); mix.connect(hp).connect(out);
            _applyGainEnvelope(mix, time, { attack: 0.001, decay: 0.08, sustain: 0.001 });
            o1.start(time); o2.start(time);
            const stopTime = time + adsr.attack + adsr.decay + adsr.release + 0.2;
            mix.gain.exponentialRampToValueAtTime(0.0001, stopTime);
            o1.stop(stopTime + 0.01); o2.stop(stopTime + 0.01);
        }
    };
    const getStepDuration = () => 60.0 / metaRef.current.bpm / 4.0;

    const scheduleStep = (stepIndex, time) => {
        const currentTracks = tracksRef.current;
        currentTracks.forEach(track => {
            const len = track.steps.length;
            const idx = stepIndex % len;
            if (track.steps[idx] === 1) {
                createDrumSoundAtTime(track.drum, track.adsr, time);
            }
        });
        const ctx = audioContextRef.current;
        const msUntil = (time - ctx.currentTime) * 1000;
        setTimeout(() => {
            if (isPlayingRef.current) {
                setVisualStep(stepIndex);
                const stepEl = document.querySelector(`.step-col-${stepIndex}`);
                if (stepEl) {
                    stepEl.scrollIntoView({ behavior: 'smooth', block: 'nearest', inline: 'nearest' });
                }
            }
        }, Math.max(0, msUntil));
    };



    const stopScheduler = () => {
        if (schedulerTimerRef.current) {
            clearInterval(schedulerTimerRef.current);
            schedulerTimerRef.current = null;
        }
    };

    const startScheduler = () => {
        if (schedulerTimerRef.current) return;
        const ctx = audioContextRef.current;
        nextNoteTimeRef.current = ctx.currentTime + 0.05;
        const lookahead = 25.0;
        const scheduleAheadTime = 0.1;

        schedulerTimerRef.current = setInterval(() => {
            const currentTime = ctx.currentTime;
            while (nextNoteTimeRef.current < currentTime + scheduleAheadTime) {
                scheduleStep(currentStepRef.current, nextNoteTimeRef.current);
                nextNoteTimeRef.current += getStepDuration();
                const totalSteps = metaRef.current.bars * 16;
                currentStepRef.current = (currentStepRef.current + 1) % totalSteps;
            }
        }, lookahead);
    };
    const togglePlayback = async () => {
        const ctx = audioContextRef.current;
        if (ctx.state === 'suspended') await ctx.resume();
        if (isPlaying) {
            setIsPlaying(false);
            stopScheduler();
            setVisualStep(-1);
        } else {
            setIsPlaying(true);
            currentStepRef.current = 0;
            startScheduler();
        }
    };

    const handleBpmChange = (e) => {
        let val = parseInt(e.target.value);
        if (isNaN(val)) val = 120;
        val = Math.max(40, Math.min(240, val));
        setMeta(prev => ({ ...prev, bpm: val }));
    };

    const addTrack = () => {
        const newTrack = {
            id: `track_${Date.now()}`,
            type: "drum",
            drum: "kick",
            steps: Array(meta.bars * 16).fill(0),
            adsr: { attack: 0.001, decay: 0.15, sustain: 0.001, release: 0.1 }
        };
        setTracks(prev => [...prev, newTrack]);
    };

    const deleteTrack = (index) => {
        setTracks(prev => prev.filter((_, i) => i !== index));
    };

    const toggleStep = (trackIndex, stepIndex) => {
        setTracks(prev => {
            const newTracks = [...prev];
            const track = { ...newTracks[trackIndex] };
            const newSteps = [...track.steps];
            newSteps[stepIndex] = newSteps[stepIndex] === 1 ? 0 : 1;
            track.steps = newSteps;
            newTracks[trackIndex] = track;
            return newTracks;
        });
    };
    const handleInstrumentButtonClick = (e, trackIndex) => {
        e.stopPropagation();

        if (instrumentPanel.isOpen && instrumentPanel.trackIndex === trackIndex) {
            setInstrumentPanel({ ...instrumentPanel, isOpen: false });
            return;
        }

        const btnRect = e.currentTarget.getBoundingClientRect();
        const containerRect = containerRef.current.getBoundingClientRect();

        const top = btnRect.bottom - containerRect.top + 5;
        const left = btnRect.left - containerRect.left;

        setInstrumentPanel({
            isOpen: true,
            trackIndex: trackIndex,
            top: top,
            left: left
        });
    };

    const changeInstrument = (drumType) => {
        if (instrumentPanel.trackIndex === null) return;

        setTracks(prev => {
            const newTracks = [...prev];
            const idx = instrumentPanel.trackIndex;
            const track = { ...newTracks[idx], drum: drumType };
            const adsr = { ...track.adsr };
            if (drumType === 'open_hat') { adsr.release = 0.5; adsr.decay = 0.18; }
            else if (drumType === 'hihat') { adsr.release = 0.02; adsr.decay = 0.04; }
            else if (drumType === 'kick') { adsr.decay = 0.12; adsr.release = 0.08; }
            track.adsr = adsr;
            newTracks[idx] = track;
            return newTracks;
        });
        setInstrumentPanel({ ...instrumentPanel, isOpen: false });
    };

    const updateAdsr = (trackIndex, param, value) => {
        setTracks(prev => {
            const newTracks = [...prev];
            newTracks[trackIndex] = {
                ...newTracks[trackIndex],
                adsr: { ...newTracks[trackIndex].adsr, [param]: parseFloat(value) }
            };
            return newTracks;
        });
    };
    const handleDragStart = (e, index) => {
        setDraggedTrackIndex(index);
        e.dataTransfer.effectAllowed = "move";
    };

    const handleDragOver = (e, index) => {
        e.preventDefault();
        setDragOverIndex(index);
    };

    const handleDrop = (e, targetIndex) => {
        e.preventDefault();
        if (draggedTrackIndex === null) return;
        const newTracks = [...tracks];
        const [removed] = newTracks.splice(draggedTrackIndex, 1);
        newTracks.splice(targetIndex, 0, removed);
        setTracks(newTracks);
        setDraggedTrackIndex(null);
        setDragOverIndex(null);
    };
    useEffect(() => {
        const handleClickOutside = (e) => {
            if (!e.target.closest('.instrument-panel') && !e.target.closest('.instrument-select-btn')) {
                setInstrumentPanel(prev => ({ ...prev, isOpen: false }));
            }
        };
        document.addEventListener('click', handleClickOutside);
        return () => document.removeEventListener('click', handleClickOutside);
    }, []);

    const totalSteps = meta.bars * 16;

    return (
        <div ref={containerRef} className="beatbox-instance-host">
            <div className="beatbox-app-container" style={{ position: 'relative' }}>
                <header className="beatbox-app-header">
                    <h1>Beatbot</h1>
                    <div className="master-controls">
                        <div className="control-group">
                            <label htmlFor="bpm">BPM</label>
                            <input
                                type="number"
                                id="bpm"
                                value={meta.bpm}
                                min="40"
                                max="240"
                                onChange={handleBpmChange}
                            />
                        </div>
                        <button
                            id="play-stop-btn"
                            className={`play-button ${isPlaying ? 'playing' : ''}`}
                            onClick={togglePlayback}
                        >
                            <svg className="icon-play" viewBox="0 0 24 24"><path d="M8 5v14l11-7z"></path></svg>
                            <svg className="icon-stop" viewBox="0 0 24 24"><path d="M6 6h12v12H6z"></path></svg>
                        </button>
                    </div>
                </header>

                <main className="sequencer" id="sequencer-container">
                    {tracks.map((track, trackIndex) => {
                        const instrument = INSTRUMENT_MAP[track.drum] || INSTRUMENT_MAP.kick;
                        const isDragging = draggedTrackIndex === trackIndex;
                        const isDragOver = dragOverIndex === trackIndex;

                        return (
                            <React.Fragment key={track.id}>
                                <div
                                    className={`track ${isDragging ? 'dragging' : ''} ${isDragOver ? 'drag-over' : ''}`}
                                    draggable
                                    onDragStart={(e) => handleDragStart(e, trackIndex)}
                                    onDragOver={(e) => handleDragOver(e, trackIndex)}
                                    onDrop={(e) => handleDrop(e, trackIndex)}
                                    onDragEnd={() => { setDraggedTrackIndex(null); setDragOverIndex(null); }}
                                >
                                    <div className="track-controls">
                                        <div style={{position: 'relative'}}>
                                            <button
                                                className="instrument-select-btn"
                                                title={instrument.name}
                                                onClick={(e) => handleInstrumentButtonClick(e, trackIndex)}
                                            >
                                                <img
                                                    src={` /icons/instruments/${instrument.icon}.svg`}
                                                    alt={instrument.name}
                                                    onError={(e) => e.target.style.display='none'}
                                                />
                                                <span style={{fontSize: '10px'}}>{instrument.icon}</span>
                                            </button>
                                        </div>

                                        <button
                                            className="control-btn"
                                            title="Настройки ADSR"
                                            onClick={(e) => {
                                                e.stopPropagation();
                                                setOpenAdsrPanel(openAdsrPanel === trackIndex ? null : trackIndex);
                                            }}
                                        >
                                            <svg viewBox="0 0 24 24"><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 1 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 1 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 9 4.6a1.65 1.65 0 0 0 1-1.51V3a2 2 0 1 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06.06a2 2 0 1 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 1 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1zM12 8a4 4 0 1 0 0 8 4 4 0 0 0 0-8z"/></svg>
                                        </button>

                                        <button
                                            className="control-btn delete-track-btn"
                                            title="Удалить дорожку"
                                            onClick={() => deleteTrack(trackIndex)}
                                        >
                                            <svg viewBox="0 0 24 24"><path d="M6 19c0 1.1.9 2 2 2h8a2 2 0 0 0 2-2V7H6v12zM19 4h-3.5l-1-1h-5l-1 1H5v2h14V4z" /></svg>
                                        </button>
                                    </div>

                                    <div className="steps-container">
                                        {Array.from({ length: totalSteps }).map((_, stepIndex) => (
                                            <div
                                                key={stepIndex}
                                                className={`step step-col-${stepIndex} ${stepIndex % 4 === 0 ? 'beat-start' : ''} ${track.steps[stepIndex] === 1 ? 'active' : ''} ${isPlaying && visualStep === stepIndex ? 'current' : ''}`}
                                                onClick={() => toggleStep(trackIndex, stepIndex)}
                                            />
                                        ))}
                                    </div>
                                </div>

                                {openAdsrPanel === trackIndex && (
                                    <div className="adsr-panel visible">
                                        {Object.keys(track.adsr).map(param => (
                                            <div key={param} className="adsr-control">
                                                <label>
                                                    <span>{param.charAt(0).toUpperCase() + param.slice(1)}</span>
                                                    <span>{track.adsr[param].toFixed(3)}s</span>
                                                </label>
                                                <input
                                                    type="range"
                                                    min="0.001"
                                                    max={param === 'release' ? 1.5 : 0.5}
                                                    step="0.001"
                                                    value={track.adsr[param]}
                                                    onChange={(e) => updateAdsr(trackIndex, param, e.target.value)}
                                                />
                                            </div>
                                        ))}
                                    </div>
                                )}
                            </React.Fragment>
                        );
                    })}
                </main>

                <footer className="beatbox-footer">
                    <button className="add-track-button" onClick={addTrack}>
                        <svg viewBox="0 0 24 24" width="20" height="20"><path d="M19 13h-6v6h-2v-6H5v-2h6V5h2v6h6v2z" /></svg>
                        <span>Добавить дорожку</span>
                    </button>
                </footer>

                {}
                {instrumentPanel.isOpen && (
                    <div
                        className="instrument-panel"
                        style={{
                            position: 'absolute',
                            top: `${instrumentPanel.top}px`,
                            left: `${instrumentPanel.left}px`,
                            zIndex: 1000 // Гарантирует перекрытие
                        }}
                    >
                        {DRUM_TYPES.map(type => (
                            <button
                                key={type}
                                className={`instrument-item ${tracks[instrumentPanel.trackIndex]?.drum === type ? 'active' : ''}`}
                                onClick={() => changeInstrument(type)}
                            >
                                <img
                                    src={` /icons/instruments/${INSTRUMENT_MAP[type].icon}.svg`}
                                    alt={INSTRUMENT_MAP[type].name}
                                    width="20"
                                />
                                <span>{INSTRUMENT_MAP[type].name}</span>
                            </button>
                        ))}
                    </div>
                )}
            </div>
        </div>
    );
};

export default Beatbox;