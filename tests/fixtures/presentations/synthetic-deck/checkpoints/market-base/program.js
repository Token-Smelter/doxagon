/* doxagon-checkpoint-registration
{"schema": "doxagon.presentation-checkpoint/1", "id": "market-base", "version": "1.0.0",
 "assets": ["asset-market-map"], "capabilities": [], "forward_to": "market-forecast",
 "description": "Base market state built from one declared asset handle."}
*/
export function create(context) {
  const image = context.root.querySelector('#market-map');
  return {
    enter() {
      const asset = context.assets.get('asset-market-map');
      if (asset === undefined) throw new Error('PRES_ASSET_UNKNOWN: asset-market-map');
      image.src = asset.url();
      image.alt = asset.alt;
      context.root.dataset.entered = context.checkpointId;
    },
    exit() {
      image.removeAttribute('src');
      delete context.root.dataset.entered;
    },
    signature() {
      return 'market-base:' + (image.getAttribute('src') === null ? 'blank' : 'asset-market-map');
    },
    inspect() {
      return { assets: Array.from(context.assets.keys()), granted: context.capabilities.granted('timers') };
    },
  };
}
