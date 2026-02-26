import { getChart } from './chartjsLoader';
import { getD3 } from './d3Loader';
import { getNomnoml } from './nomnomlLoader';
import { getMermaid } from './mermaidLoader';



let mermaidConfigured = false;

const setupPanZoom = (container, target, options = {}) => {
    if (!container || !target) return;
    if (container.dataset.hasPan) return;

    const {
        minScale = 0.2,
        maxScale = 5,
        zoomSpeed = 0.1,
        activeClass = 'pan-enabled',
        panningClass = 'is-panning'
    } = options;

    container.dataset.hasPan = '1';
    container.classList.add(activeClass);
    container.style.touchAction = 'none';
    target.dataset.panBound = '1';

    target.style.transformOrigin = '0 0';
    target.style.transition = 'none';

    let state = {
        panning: false,
        scale: 1,
        x: 0,
        y: 0,
        startX: 0,
        startY: 0
    };

    const updateTransform = () => {
        target.style.transform = `matrix(${state.scale}, 0, 0, ${state.scale}, ${state.x}, ${state.y})`;
    };

    container.addEventListener('dblclick', () => {
        state.scale = 1;
        state.x = 0;
        state.y = 0;
        target.style.transition = 'transform 0.3s ease-out';
        updateTransform();
        setTimeout(() => { target.style.transition = 'none'; }, 300);
    });

    const onPointerDown = (e) => {
        if (e.pointerType === 'mouse' && e.button !== 0) return;

        state.panning = true;
        state.startX = e.clientX - state.x;
        state.startY = e.clientY - state.y;
        container.classList.add(panningClass);

        try {
            container.setPointerCapture(e.pointerId);
        } catch { }
        e.preventDefault();
    };

    const onPointerMove = (e) => {
        if (!state.panning) return;

        state.x = e.clientX - state.startX;
        state.y = e.clientY - state.startY;
        updateTransform();
        e.preventDefault();
    };

    const onPointerUp = (e) => {
        if (!state.panning) return;
        state.panning = false;
        container.classList.remove(panningClass);

        try {
            if (container.releasePointerCapture) {
                container.releasePointerCapture(e.pointerId);
            }
        } catch { }
        e.preventDefault();
    };

    const onWheel = (e) => {
        if (e.ctrlKey || e.metaKey || e.altKey) return;

        e.preventDefault();
        e.stopPropagation();

        const rect = container.getBoundingClientRect();
        const offsetX = e.clientX - rect.left;
        const offsetY = e.clientY - rect.top;

        const delta = -Math.sign(e.deltaY);
        let newScale = state.scale + delta * zoomSpeed;
        newScale = Math.max(minScale, Math.min(maxScale, newScale));

        const targetX = (offsetX - state.x) / state.scale;
        const targetY = (offsetY - state.y) / state.scale;

        state.x = offsetX - targetX * newScale;
        state.y = offsetY - targetY * newScale;
        state.scale = newScale;

        updateTransform();
    };

    container.addEventListener('pointerdown', onPointerDown);
    container.addEventListener('pointermove', onPointerMove);
    container.addEventListener('pointerup', onPointerUp);
    container.addEventListener('pointercancel', onPointerUp);
    container.addEventListener('wheel', onWheel, { passive: false });
    target.addEventListener('dragstart', (e) => e.preventDefault());
};

export const Utils = {
    escapeHtml: (str) => {
        if (typeof str !== 'string') return '';
        return str
            .replace(/&/g, "&amp;")
            .replace(/</g, "&lt;")
            .replace(/>/g, "&gt;")
            .replace(/"/g, "&quot;")
            .replace(/'/g, "&#039;");
    },

    addTempAnimation: (element, className, durationMs = 1000) => {
        if (!(element instanceof HTMLElement) || !className) return;
        element.classList.add(className);
        const remove = () => element.classList.remove(className);
        element.addEventListener('animationend', remove, { once: true });
        setTimeout(remove, durationMs);
    },

    flashElement: (element, type = 'warning') => {
        if (!(element instanceof HTMLElement)) return;
        const map = {
            warning: 'attention-flash',
            error: 'shake',
            info: 'pulse-once',
            success: 'pulse-once'
        };
        const cls = map[type] || 'attention-flash';
        Utils.addTempAnimation(element, cls);
    },

    autoResizeTextarea: (textarea, minHeight = 70, maxHeight = 190) => {
        if (!textarea || typeof textarea.style === 'undefined') return;
        textarea.style.height = 'auto';
        requestAnimationFrame(() => {
            const scrollHeight = textarea.scrollHeight || minHeight;
            const cssMinHeight = parseFloat(getComputedStyle(textarea).getPropertyValue('--input-area-item-height')) || 46;
            const effectiveMinHeight = Math.max(minHeight, cssMinHeight);
            const newHeight = Math.max(effectiveMinHeight, Math.min(scrollHeight, maxHeight));
            textarea.style.height = `${newHeight}px`;
        });
    },

    copyToClipboard: async (text, buttonElement) => {
        if (!navigator.clipboard) {
            Utils.showPopupWarning('Копирование не поддерживается вашим браузером.');
            return;
        }
        try {
            await navigator.clipboard.writeText(text);
            if (buttonElement) {
                buttonElement.classList.add('copied');
                Utils.addTempAnimation(buttonElement, 'pulse-once', 600);
                Utils.flashElement(buttonElement, 'success');
                setTimeout(() => buttonElement.classList.remove('copied'), 800);
            }
        } catch (err) {
            console.error('Ошибка копирования:', err);
            Utils.showPopupWarning('Не удалось скопировать текст.');
            if (buttonElement) {
                Utils.addTempAnimation(buttonElement, 'shake', 500);
                Utils.flashElement(buttonElement, 'error');
            }
        }
    },

    showPopupWarning: () => {
        const active = document.activeElement?.closest('button, .action-btn, .send-button, .attach-button');
        const preview = document.querySelector('.attach-area .preview-container');
        const sendBtn = document.querySelector('.send-button');
        const target = active || preview || sendBtn || document.body;
        Utils.flashElement(target, active ? 'error' : 'warning');
    },

    getRandomPhrase: (phrasesArray, defaultPhrase) => {
        if (!Array.isArray(phrasesArray) || phrasesArray.length === 0) return defaultPhrase;
        const validPhrases = phrasesArray.filter(p => typeof p === 'string' && p.trim() !== '');
        return validPhrases.length > 0 ? validPhrases[Math.floor(Math.random() * validPhrases.length)] : defaultPhrase;
    },

    getFileIconPath: (ext) => {
        const ICON_CDN_BASE_URL = 'https://cdn.jsdelivr.net/gh/vscode-icons/vscode-icons/icons/file_type_';
        const iconMap = {
            'js': 'js', 'py': 'python', 'html': 'html', 'css': 'css', 'json': 'json', 'txt': 'text',
            'cpp': 'cpp', 'c': 'c', 'cs': 'csharp', 'java': 'java', 'php': 'php', 'rb': 'ruby',
            'swift': 'swift', 'kt': 'kotlin', 'go': 'go', 'rs': 'rust', 'ts': 'typescript',
            'md': 'markdown', 'xml': 'xml', 'yaml': 'yaml', 'yml': 'yaml', 'sh': 'shell',
            'bat': 'bat', 'ps1': 'powershell', 'pl': 'perl', 'dart': 'dart', 'lua': 'lua',
            'r': 'r', 'scala': 'scala', 'hs': 'haskell', 'erl': 'erlang', 'clj': 'clojure',
            'ex': 'elixir', 'zig': 'zig', 'pdf': 'pdf', 'doc': 'word', 'docx': 'word',
            'xls': 'excel', 'xlsx': 'excel', 'ppt': 'powerpoint', 'pptx': 'powerpoint',
            'zip': 'zip', 'rar': 'zip', 'tar': 'zip', 'gz': 'zip', '7z': 'zip',
            'iso': 'disk', 'exe': 'exe', 'dmg': 'disk', 'apk': 'android',
            'svg': 'svg', 'webp': 'image', 'ico': 'image', 'gif': 'image',
            'png': 'image', 'jpg': 'image', 'jpeg': 'image',
            'mp3': 'audio', 'wav': 'audio', 'ogg': 'audio', 'flac': 'audio',
            'mp4': 'video', 'mkv': 'video', 'avi': 'video', 'mov': 'video', 'webm': 'video',
            'ino': 'arduino'
        };
        const iconName = iconMap[ext?.toLowerCase() || ''];
        return iconName ? `${ICON_CDN_BASE_URL}${iconName}.svg` : 'https://cdn.jsdelivr.net/gh/vscode-icons/vscode-icons/icons/default_file.svg';
    },

    downloadFile: (content, filename, mimeType = 'text/plain') => {
        const blob = new Blob([content], { type: mimeType });
        const url = window.URL.createObjectURL(blob);
        const link = document.createElement('a');
        link.href = url;
        link.download = filename;
        document.body.appendChild(link);
        link.click();
        document.body.removeChild(link);
        window.URL.revokeObjectURL(url);
    },

    debounce: (func, wait) => {
        let timeout;
        return function (...args) {
            clearTimeout(timeout);
            timeout = setTimeout(() => func.apply(this, args), wait);
        };
    },

    hasUnclosedCodeFence: (text) => {
        if (typeof text !== 'string') return false;
        const matches = text.match(/```/g);
        return matches ? (matches.length % 2 === 1) : false;
    },

    attachDiagramPan: () => {
        document.querySelectorAll('.diagram-pan-surface').forEach(container => {
            if (container.dataset.hasPan) return;
            const target = container.querySelector('.diagram-pan-target') || container.querySelector('canvas, svg');
            if (!target) return;
            setupPanZoom(container, target);
        });
    },

    renderCharts: async () => {
        const containers = document.querySelectorAll('.chart-container');
        if (!containers.length) return;

        let Chart;
        try {
            Chart = await getChart();
        } catch (error) {
            console.warn('Chart.js load failed:', error);
            containers.forEach(container => {
                const loadingEl = container.querySelector('.chart-loading');
                const errorEl = container.querySelector('.chart-error');
                if (loadingEl) loadingEl.style.display = 'none';
                if (errorEl) {
                    errorEl.textContent = 'Не удалось загрузить Chart.js';
                    errorEl.style.display = 'flex';
                }
                container.classList.remove('loading');
            });
            return;
        }

        containers.forEach(container => {
            const canvas = container.querySelector('canvas');
            const loadingEl = container.querySelector('.chart-loading');
            const errorEl = container.querySelector('.chart-error');
            const codeBlock = container.closest('.code-block');
            if (!canvas || !loadingEl || !codeBlock) return;

            try {
                const codeElement = codeBlock.querySelector('.code-block-content code');
                if (!codeElement) {
                    if (loadingEl) loadingEl.style.display = 'none';
                    if (errorEl) {
                        errorEl.textContent = 'Код графика не найден';
                        errorEl.style.display = 'flex';
                    }
                    container.classList.remove('loading');
                    return;
                }

                let chartData = JSON.parse(codeElement.textContent || '{}');
                if (!chartData.type || !chartData.data) {
                    if (loadingEl) loadingEl.style.display = 'none';
                    if (errorEl) {
                        errorEl.textContent = 'Неверный формат данных графика';
                        errorEl.style.display = 'flex';
                    }
                    container.classList.remove('loading');
                    return;
                }

                if (chartData.options && chartData.options.scales) {
                    if (chartData.options.scales.yAxes) {
                        const yAxis = chartData.options.scales.yAxes;
                        chartData.options.scales.y = {
                            ...yAxis,
                            beginAtZero: yAxis.ticks?.beginAtZero || false
                        };
                        delete chartData.options.scales.yAxes;
                    }
                    if (chartData.options.scales.xAxes) {
                        const xAxis = chartData.options.scales.xAxes;
                        chartData.options.scales.x = { ...xAxis };
                        delete chartData.options.scales.xAxes;
                    }
                }

                if (canvas.__chartInstance && typeof canvas.__chartInstance.destroy === 'function') {
                    canvas.__chartInstance.destroy();
                }

                loadingEl.style.display = 'none';
                if (errorEl) {
                    errorEl.textContent = '';
                    errorEl.style.display = 'none';
                }
                container.classList.remove('loading');

                const chart = new Chart(canvas, {
                    type: chartData.type,
                    data: chartData.data,
                    options: {
                        responsive: true,
                        maintainAspectRatio: false,
                        plugins: {
                            legend: {
                                position: 'top',
                                labels: {
                                    color: getComputedStyle(document.documentElement).getPropertyValue('--text-color') || '#ffffff'
                                }
                            },
                            title: {
                                display: true,
                                text: chartData.title || 'График',
                                color: getComputedStyle(document.documentElement).getPropertyValue('--text-color') || '#ffffff'
                            }
                        },
                        scales: {
                            x: {
                                ticks: {
                                    color: getComputedStyle(document.documentElement).getPropertyValue('--text-color') || '#ffffff'
                                },
                                grid: {
                                    color: getComputedStyle(document.documentElement).getPropertyValue('--border-color') || '#444444'
                                }
                            },
                            y: {
                                ticks: {
                                    color: getComputedStyle(document.documentElement).getPropertyValue('--text-color') || '#ffffff'
                                },
                                grid: {
                                    color: getComputedStyle(document.documentElement).getPropertyValue('--border-color') || '#444444'
                                }
                            }
                        },
                        ...chartData.options
                    }
                });
                canvas.__chartInstance = chart;
            } catch (e) {
                console.warn('Chart.js rendering error:', e);
                if (loadingEl) loadingEl.style.display = 'none';
                if (errorEl) {
                    errorEl.textContent = 'Ошибка загрузки графика: ' + e.message;
                    errorEl.style.display = 'flex';
                }
                container.classList.remove('loading');
            }
        });
    },

    renderD3: async () => {
        const containers = document.querySelectorAll('.d3-container');
        if (!containers.length) return;

        let d3;
        try {
            d3 = await getD3();
        } catch (error) {
            console.warn('D3 load failed:', error);
            containers.forEach(container => {
                const loadingEl = container.querySelector('.d3-loading');
                const errorEl = container.querySelector('.d3-error');
                if (loadingEl) loadingEl.style.display = 'none';
                if (errorEl) {
                    errorEl.textContent = 'Не удалось загрузить D3.js';
                    errorEl.style.display = 'flex';
                }
                container.classList.remove('loading');
            });
            return;
        }

        const rootStyles = getComputedStyle(document.documentElement);
        const textColor = rootStyles.getPropertyValue('--color-text-primary') || '#ffffff';
        const secondaryText = rootStyles.getPropertyValue('--color-text-secondary') || 'rgba(255,255,255,0.7)';
        const gridColor = rootStyles.getPropertyValue('--color-border-subtle') || 'rgba(255,255,255,0.2)';
        const accentColor = rootStyles.getPropertyValue('--color-accent') || '#7c9cff';
        const palette = d3.schemeTableau10 || ['#7c9cff', '#a78bfa', '#60a5fa', '#34d399', '#fbbf24'];

        containers.forEach(container => {
            const loadingEl = container.querySelector('.d3-loading');
            const errorEl = container.querySelector('.d3-error');
            const viz = container.querySelector('.d3-visualization');
            const codeBlock = container.closest('.code-block');
            if (!viz || !codeBlock) return;

            const codeElement = codeBlock.querySelector('.code-block-content code');
            if (!codeElement) {
                if (loadingEl) loadingEl.style.display = 'none';
                if (errorEl) {
                    errorEl.textContent = 'Код визуализации не найден';
                    errorEl.style.display = 'flex';
                }
                container.classList.remove('loading');
                return;
            }

            let config;
            try {
                config = JSON.parse(codeElement.textContent || '{}');
            } catch (e) {
                if (loadingEl) loadingEl.style.display = 'none';
                if (errorEl) {
                    errorEl.textContent = 'Неверный JSON для D3';
                    errorEl.style.display = 'flex';
                }
                container.classList.remove('loading');
                return;
            }

            const type = (config.type || '').toLowerCase();
            const data = Array.isArray(config.data) ? config.data : [];
            const width = Math.max(320, container.clientWidth || 640);
            const height = 320;
            const margin = { top: 20, right: 24, bottom: 36, left: 48 };

            container.classList.add('loading');
            if (loadingEl) loadingEl.style.display = 'flex';
            if (errorEl) {
                errorEl.textContent = '';
                errorEl.style.display = 'none';
            }

            viz.innerHTML = '';

            const svg = d3.select(viz)
                .append('svg')
                .attr('width', width)
                .attr('height', height)
                .attr('viewBox', `0 0 ${width} ${height}`)
                .attr('class', 'diagram-pan-target');

            const styleAxis = () => {
                svg.selectAll('text')
                    .attr('fill', secondaryText)
                    .attr('font-size', 11);
                svg.selectAll('path, line')
                    .attr('stroke', gridColor);
            };

            try {
                if (!data.length) {
                    throw new Error('Нет данных');
                }
                if (type === 'pie') {
                    const values = data.map((d) => (typeof d === 'number' ? d : (d.value ?? d.y ?? 0)));
                    const labels = data.map((d, i) => (typeof d === 'object' ? (d.label || d.name || `${i + 1}`) : `${i + 1}`));
                    const radius = Math.min(width, height) / 2 - 12;
                    const pie = d3.pie()(values);
                    const arc = d3.arc().innerRadius(0).outerRadius(radius);

                    const g = svg.append('g')
                        .attr('transform', `translate(${width / 2},${height / 2})`);

                    g.selectAll('path')
                        .data(pie)
                        .enter()
                        .append('path')
                        .attr('d', arc)
                        .attr('fill', (d, i) => palette[i % palette.length])
                        .attr('stroke', 'rgba(0,0,0,0.1)');

                    g.selectAll('text')
                        .data(pie)
                        .enter()
                        .append('text')
                        .text((d, i) => labels[i] || '')
                        .attr('transform', (d) => `translate(${arc.centroid(d)})`)
                        .attr('text-anchor', 'middle')
                        .attr('font-size', 11)
                        .attr('fill', textColor);
                } else if (type === 'line' || type === 'scatter') {
                    const points = data.map((d, i) => {
                        if (typeof d === 'number') return { x: i, y: d };
                        return {
                            x: d.x ?? i,
                            y: d.y ?? d.value ?? 0
                        };
                    });

                    const xExtent = d3.extent(points, d => d.x);
                    const yExtent = d3.extent(points, d => d.y);

                    const x = d3.scaleLinear()
                        .domain(xExtent[0] === xExtent[1] ? [xExtent[0] - 1, xExtent[1] + 1] : xExtent)
                        .range([margin.left, width - margin.right]);

                    const y = d3.scaleLinear()
                        .domain(yExtent[0] === yExtent[1] ? [yExtent[0] - 1, yExtent[1] + 1] : yExtent)
                        .nice()
                        .range([height - margin.bottom, margin.top]);

                    svg.append('g')
                        .attr('transform', `translate(0,${height - margin.bottom})`)
                        .call(d3.axisBottom(x).ticks(5));
                    svg.append('g')
                        .attr('transform', `translate(${margin.left},0)`)
                        .call(d3.axisLeft(y).ticks(5));
                    styleAxis();

                    if (type === 'line') {
                        const line = d3.line()
                            .x(d => x(d.x))
                            .y(d => y(d.y));

                        svg.append('path')
                            .datum(points)
                            .attr('fill', 'none')
                            .attr('stroke', accentColor)
                            .attr('stroke-width', 2)
                            .attr('d', line);
                    }

                    svg.append('g')
                        .selectAll('circle')
                        .data(points)
                        .enter()
                        .append('circle')
                        .attr('cx', d => x(d.x))
                        .attr('cy', d => y(d.y))
                        .attr('r', 4)
                        .attr('fill', accentColor);
                } else if (type === 'bar') {
                    const labels = data.map((d, i) => (typeof d === 'object' ? (d.label || d.name || `${i + 1}`) : `${i + 1}`));
                    const values = data.map((d) => (typeof d === 'number' ? d : (d.value ?? d.y ?? 0)));

                    const x = d3.scaleBand()
                        .domain(labels)
                        .range([margin.left, width - margin.right])
                        .padding(0.2);

                    const y = d3.scaleLinear()
                        .domain([0, d3.max(values) || 0])
                        .nice()
                        .range([height - margin.bottom, margin.top]);

                    svg.append('g')
                        .attr('transform', `translate(0,${height - margin.bottom})`)
                        .call(d3.axisBottom(x));
                    svg.append('g')
                        .attr('transform', `translate(${margin.left},0)`)
                        .call(d3.axisLeft(y).ticks(5));
                    styleAxis();

                    svg.append('g')
                        .selectAll('rect')
                        .data(values)
                        .enter()
                        .append('rect')
                        .attr('x', (_, i) => x(labels[i]))
                        .attr('y', d => y(d))
                        .attr('height', d => y(0) - y(d))
                        .attr('width', x.bandwidth())
                        .attr('fill', accentColor);
                } else {
                    throw new Error('Unsupported D3 type');
                }

                container.classList.remove('loading');
                if (loadingEl) loadingEl.style.display = 'none';
            } catch (error) {
                console.warn('D3 render failed:', error);
                if (loadingEl) loadingEl.style.display = 'none';
                if (errorEl) {
                    errorEl.textContent = 'Ошибка визуализации D3: ' + error.message;
                    errorEl.style.display = 'flex';
                }
                container.classList.remove('loading');
            }
        });
    },

    renderNomnoml: async () => {
        const containers = document.querySelectorAll('.nomnoml-container');
        if (!containers.length) return;

        let nomnoml;
        try {
            nomnoml = await getNomnoml();
        } catch (error) {
            console.warn('Nomnoml load failed:', error);
            containers.forEach(container => {
                const loadingEl = container.querySelector('.nomnoml-loading');
                const errorEl = container.querySelector('.nomnoml-error');
                if (loadingEl) loadingEl.style.display = 'none';
                if (errorEl) {
                    errorEl.textContent = 'Не удалось загрузить Nomnoml';
                    errorEl.style.display = 'flex';
                }
                container.classList.remove('loading');
            });
            return;
        }

        containers.forEach(container => {
            const loadingEl = container.querySelector('.nomnoml-loading');
            const errorEl = container.querySelector('.nomnoml-error');
            const viz = container.querySelector('.nomnoml-visualization');
            const codeBlock = container.closest('.code-block');
            if (!viz || !codeBlock) return;

            const codeElement = codeBlock.querySelector('.code-block-content code');
            if (!codeElement) {
                if (loadingEl) loadingEl.style.display = 'none';
                if (errorEl) {
                    errorEl.textContent = 'Код схемы не найден';
                    errorEl.style.display = 'flex';
                }
                container.classList.remove('loading');
                return;
            }

            container.classList.add('loading');
            if (loadingEl) loadingEl.style.display = 'flex';
            if (errorEl) {
                errorEl.textContent = '';
                errorEl.style.display = 'none';
            }

            try {
                const svgText = nomnoml.renderSvg(codeElement.textContent || '');
                viz.innerHTML = svgText;
                const svg = viz.querySelector('svg');
                if (svg) {
                    svg.classList.add('diagram-pan-target');
                    svg.setAttribute('role', 'img');
                    svg.setAttribute('aria-label', 'Nomnoml diagram');
                    if (!svg.getAttribute('viewBox')) {
                        const width = svg.getAttribute('width') || 640;
                        const height = svg.getAttribute('height') || 360;
                        svg.setAttribute('viewBox', `0 0 ${width} ${height}`);
                    }
                }

                container.classList.remove('loading');
                if (loadingEl) loadingEl.style.display = 'none';
            } catch (error) {
                console.warn('Nomnoml render failed:', error);
                if (loadingEl) loadingEl.style.display = 'none';
                if (errorEl) {
                    errorEl.textContent = 'Ошибка схемы Nomnoml: ' + error.message;
                    errorEl.style.display = 'flex';
                }
                container.classList.remove('loading');
            }
        });
    },

    renderMermaid: async () => {
        const containers = document.querySelectorAll('.mermaid-container');
        if (!containers.length) return;

        let mermaid;
        try {
            mermaid = await getMermaid();
            if (!mermaidConfigured) {
                mermaid.initialize({
                    startOnLoad: false,
                    securityLevel: 'strict'
                });
                mermaidConfigured = true;
            }
        } catch (error) {
            console.warn('Mermaid load failed:', error);
            containers.forEach(container => {
                const loadingEl = container.querySelector('.mermaid-loading');
                const errorEl = container.querySelector('.mermaid-error');
                if (loadingEl) loadingEl.style.display = 'none';
                if (errorEl) {
                    errorEl.textContent = 'Не удалось загрузить Mermaid';
                    errorEl.style.display = 'flex';
                }
                container.classList.remove('loading');
            });
            return;
        }

        let renderIndex = 0;
        for (const container of containers) {
            const loadingEl = container.querySelector('.mermaid-loading');
            const errorEl = container.querySelector('.mermaid-error');
            const viz = container.querySelector('.mermaid-visualization');
            const codeBlock = container.closest('.code-block');
            if (!viz || !codeBlock) continue;

            const codeElement = codeBlock.querySelector('.code-block-content code');
            if (!codeElement) {
                if (loadingEl) loadingEl.style.display = 'none';
                if (errorEl) {
                    errorEl.textContent = 'Код диаграммы не найден';
                    errorEl.style.display = 'flex';
                }
                container.classList.remove('loading');
                continue;
            }

            const diagramText = (codeElement.textContent || '').trim();
            if (!diagramText) {
                if (loadingEl) loadingEl.style.display = 'none';
                if (errorEl) {
                    errorEl.textContent = 'Пустой Mermaid блок';
                    errorEl.style.display = 'flex';
                }
                container.classList.remove('loading');
                continue;
            }

            container.classList.add('loading');
            if (loadingEl) loadingEl.style.display = 'flex';
            if (errorEl) {
                errorEl.textContent = '';
                errorEl.style.display = 'none';
            }

            try {
                const renderId = `mermaid-${Date.now()}-${renderIndex++}`;
                const result = await mermaid.render(renderId, diagramText);
                // Safely parse the SVG string instead of assigning it directly to innerHTML
                while (viz.firstChild) {
                    viz.removeChild(viz.firstChild);
                }

                const svgContent = result?.svg || '';
                if (svgContent) {
                    const parser = new DOMParser();
                    const doc = parser.parseFromString(svgContent, 'image/svg+xml');
                    const parsedSvg = doc.querySelector('svg');
                    if (parsedSvg) {
                        viz.appendChild(parsedSvg);
                    }
                }

                if (typeof result?.bindFunctions === 'function') {
                    result.bindFunctions(viz);
                }

                const svg = viz.querySelector('svg');
                if (svg) {
                    const parseSvgSize = (value) => {
                        if (!value) return null;
                        const num = parseFloat(String(value).replace('px', ''));
                        return Number.isFinite(num) ? num : null;
                    };
                    const pad = 12;
                    const widthAttr = parseSvgSize(svg.getAttribute('width'));
                    const heightAttr = parseSvgSize(svg.getAttribute('height'));
                    if (!svg.getAttribute('viewBox')) {
                        const bbox = svg.getBBox();
                        const vbX = Number.isFinite(bbox.x) ? bbox.x - pad : 0;
                        const vbY = Number.isFinite(bbox.y) ? bbox.y - pad : 0;
                        const vbWidth = (bbox.width || widthAttr || 640) + pad * 2;
                        const vbHeight = (bbox.height || heightAttr || 360) + pad * 2;
                        svg.setAttribute('viewBox', `${vbX} ${vbY} ${vbWidth} ${vbHeight}`);
                    }
                    svg.classList.add('diagram-pan-target');
                    svg.setAttribute('role', 'img');
                    svg.setAttribute('aria-label', 'Mermaid diagram');
                    svg.setAttribute('width', '100%');
                    svg.setAttribute('height', '100%');
                    svg.setAttribute('preserveAspectRatio', 'xMidYMid meet');
                }

                container.classList.remove('loading');
                if (loadingEl) loadingEl.style.display = 'none';
            } catch (error) {
                console.warn('Mermaid render failed:', error);
                if (loadingEl) loadingEl.style.display = 'none';
                if (errorEl) {
                    errorEl.textContent = 'Ошибка схемы Mermaid: ' + error.message;
                    errorEl.style.display = 'flex';
                }
                container.classList.remove('loading');
            }
        }
    },
};
