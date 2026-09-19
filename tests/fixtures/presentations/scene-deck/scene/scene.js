const positions = {
    'shape-start': [30, 40],
    'shape-moved': [150, 40],
    'shape-morphed': [250, 70],
    'shape-failed': [300, 40],
    'shape-stalled': [350, 70],
    'shape-wrong': [380, 40],
    'other-scene': [30, 90],
};

window.createExampleScene = function createExampleScene(context) {
    const shape = context.root.querySelector('rect');
    const image = context.root.querySelector('image');
    const pulse = context.root.querySelector('circle');
    let current = context.checkpointId;
    let ticks = 0;
    let transitions = 0;
    let direction = '';
    let simulation = null;
    let position = [...positions[current]];
    let samples = 0;
    let sampled = null;
    const sweep = context.root.querySelector('circle.sweep');

    function draw(x, y) {
        position = [x, y];
        shape.setAttribute('x', String(x));
        shape.setAttribute('y', String(y));
        shape.setAttribute('rx', String(Math.max(0, (x - 150) / 5)));
        image.setAttribute('x', String(x + 45));
        image.setAttribute('y', String(y));
    }

    return {
        enter() {
            image.setAttribute('href', context.assets.get('asset-market-map').url());
            draw(...positions[current]);
            if (!context.reducedMotion) {
                simulation = context.capabilities.interval(() => {
                    ticks += 1;
                    pulse.setAttribute('r', String(4 + ticks % 6));
                }, 30);
            }
        },
        async transition({ from, to, direction: travel, signal }) {
            if (from !== current) throw new Error('scene lost its source');
            transitions += 1;
            direction = travel;
            if (travel === 'forward' && to === 'shape-failed') throw new Error('authored failure');
            if (travel === 'forward' && to === 'shape-stalled') return new Promise(() => {});
            if (travel === 'forward' && to === 'shape-wrong') {
                draw(0, 0);
                current = to;
                return;
            }
            const start = [...position];
            const end = positions[to];
            await new Promise((resolve, reject) => {
                let frame = null;
                let began = null;
                const aborted = () => {
                    if (frame !== null) context.capabilities.release(frame);
                    reject(new Error('animation aborted'));
                };
                signal.addEventListener('abort', aborted, { once: true });
                function tick(time) {
                    began ??= time;
                    const progress = Math.min(1, (time - began) / 400);
                    // Back takes its own curved route rather than inverting Next.
                    const arc = travel === 'reverse' ? Math.sin(progress * Math.PI) * 40 : 0;
                    draw(start[0] + (end[0] - start[0]) * progress, start[1] + (end[1] - start[1]) * progress + arc);
                    if (progress === 1) {
                        signal.removeEventListener('abort', aborted);
                        resolve();
                    } else frame = context.capabilities.frame(tick);
                }
                frame = context.capabilities.frame(tick);
            });
            draw(...end);
            current = to;
        },
        // A sampled track is content driven by continuous progress. It moves
        // its own element so cue signatures stay independent of scroll input.
        sample({ track, progress }) {
            if (track !== 'sweep') return;
            samples += 1;
            sampled = progress;
            sweep.setAttribute('cx', String(Math.round(30 + progress * 300)));
        },
        signature() {
            return `${current}:${position.join(',')}:${shape.getAttribute('rx')}`;
        },
        inspect() {
            return { current, ticks, transitions, direction, position, contextId: context.checkpointId,
                handles: context.capabilities.openHandles(), samples, sampled,
                sweep: Number(sweep.getAttribute('cx')) };
        },
        exit() {
            if (simulation !== null) context.capabilities.release(simulation);
        },
    };
};
