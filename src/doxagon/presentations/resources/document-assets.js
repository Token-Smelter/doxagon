/* Inline after the complete lightweight document structure, before image payloads. */
(() => {
    'use strict';
    const slots = [...document.querySelectorAll('img[data-dox-asset]')];
    const payloads = new Map();
    const wanted = new Set();
    const status = document.getElementById('asset-status');
    let activeChapter = slots[0]?.closest('.chapter')?.id;
    let complete = false;
    let interrupted = false;

    function activeSlots() {
        return slots.filter(image => image.closest('.chapter')?.id === activeChapter);
    }

    function updateStatus() {
        if (!status) return;
        const current = activeSlots();
        const failed = current.some(image => image.dataset.assetError === 'true');
        const waiting = current.some(image => !image.complete || image.naturalWidth === 0);
        const missing = current.some(image => !payloads.has(image.dataset.doxAsset));
        status.textContent = interrupted
            ? 'Download interrupted. Reload the presentation to finish.'
            : failed || (complete && missing)
                ? 'An image is unavailable. Reload the presentation to retry.'
                : waiting ? 'Images for this chapter are downloading…' : '';
        status.hidden = !status.textContent;
    }

    function attach(image) {
        const id = image.dataset.doxAsset;
        if (image.hasAttribute('src') || !wanted.has(id) || !payloads.has(id)) return;
        image.addEventListener('load', updateStatus, { once: true });
        image.addEventListener('error', () => {
            image.dataset.assetError = 'true';
            updateStatus();
        }, { once: true });
        image.src = payloads.get(id);
    }

    function requestWindow(chapter) {
        activeChapter = chapter;
        const current = activeSlots();
        if (current.length) {
            const last = slots.indexOf(current[current.length - 1]);
            for (const image of [...current, ...slots.slice(last + 1, last + 3)]) {
                wanted.add(image.dataset.doxAsset);
            }
        }
        // Once attached, an image stays attached. No per-cue DOM reconstruction
        // or eviction-induced flashes when stepping backward.
        slots.forEach(attach);
        updateStatus();
    }

    window.doxagonAssets = Object.freeze({
        receive(figure) {
            const image = figure?.querySelector('img');
            const id = figure?.dataset.doxSource;
            const source = image?.getAttribute('src');
            if (!id || !slots.some(slot => slot.dataset.doxAsset === id)
                || !/^data:image\/(?:webp|png|jpeg|gif);base64,[A-Za-z0-9+/=]+$/.test(source || '')) {
                interrupted = true;
                updateStatus();
                return;
            }
            payloads.set(id, source);
            // Without JS the payload figures are a visible image appendix.
            // With JS the same bytes hydrate the authored image slots instead.
            figure.remove();
            slots.forEach(attach);
            updateStatus();
        },
        complete() {
            complete = true;
            document.documentElement.dataset.assetsComplete = 'true';
            updateStatus();
        },
        state() {
            return {
                total: new Set(slots.map(image => image.dataset.doxAsset)).size,
                received: payloads.size,
                attached: slots.filter(image => image.hasAttribute('src')).length,
                complete,
                interrupted,
            };
        },
    });
    window.addEventListener('doxagon:position', event => requestWindow(event.detail.chapter));
    window.addEventListener('load', () => {
        if (!complete) interrupted = true;
        updateStatus();
    }, { once: true });
    window.addEventListener('beforeprint', () => {
        slots.forEach(image => wanted.add(image.dataset.doxAsset));
        slots.forEach(attach);
    });
    requestWindow(activeChapter);
})();
