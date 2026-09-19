window.createFieldDocument = function createFieldDocument(context) {
    const field = context.root.querySelector('#field');
    const clusters = context.root.querySelector('#clusters');
    const legend = Array.from(context.root.querySelectorAll('.legend li'));
    const seeded = (seed) => () => ((seed = (seed * 1103515245 + 12345) & 0x7fffffff) / 0x7fffffff);
    const random = seeded(7);
    const points = Array.from({ length: 260 }, () => ({
        sx: random(), sy: random(), cx: random(), cy: random(), phase: random() * Math.PI * 2,
        region: Math.floor(random() * 3),
    }));
    let drift = 0;
    let focus = 0;
    let ticks = 0;
    let cue = context.checkpointId;
    let hovered = -1;
    let loop = null;

    function paint(canvas, blend, highlight) {
        if (canvas === null) return;
        const scale = Math.min(window.devicePixelRatio || 1, 2);
        const width = canvas.clientWidth * scale;
        const height = canvas.clientHeight * scale;
        if (canvas.width !== width || canvas.height !== height) { canvas.width = width; canvas.height = height; }
        const draw = canvas.getContext('2d');
        draw.clearRect(0, 0, width, height);
        for (const point of points) {
            const breathe = Math.sin(point.phase + ticks / 24) * 0.01;
            const x = (point.sx + (point.cx - point.sx) * blend + breathe) * width;
            const y = (point.sy + (point.cy - point.sy) * blend + breathe) * height;
            const lit = highlight < 0 || point.region === highlight;
            draw.globalAlpha = lit ? 0.85 : 0.15;
            draw.fillStyle = lit ? '#e08a4c' : '#7f8a96';
            draw.beginPath();
            draw.arc(x, y, (lit ? 2.6 : 1.8) * scale, 0, Math.PI * 2);
            draw.fill();
        }
    }

    function render() {
        paint(field, drift, -1);
        paint(clusters, Math.max(drift, focus), hovered);
    }

    for (const item of legend) {
        const region = Number(item.dataset.region);
        const enter = () => { hovered = region; legend.forEach((node) => node.setAttribute('aria-current', String(node === item))); render(); };
        const leave = () => { hovered = -1; legend.forEach((node) => node.removeAttribute('aria-current')); render(); };
        item.addEventListener('pointerenter', enter);
        item.addEventListener('pointerleave', leave);
        item.addEventListener('click', enter);
    }

    return {
        enter() {
            render();
            if (!context.reducedMotion) {
                // A dwell loop: the field keeps breathing while the reader rests.
                loop = context.capabilities.interval(() => { ticks += 1; render(); }, 40);
            }
        },
        sample({ track, progress }) {
            if (track === 'drift') drift = progress;
            if (track === 'focus') focus = progress;
            render();
        },
        cue({ cue: entered }) { cue = entered; },
        signature() { return `${context.checkpointId}:${points.length}`; },
        inspect() {
            return { cue, drift: Math.round(drift * 100) / 100, focus: Math.round(focus * 100) / 100,
                ticks, hovered, handles: context.capabilities.openHandles() };
        },
        exit() { if (loop !== null) context.capabilities.release(loop); },
    };
};
