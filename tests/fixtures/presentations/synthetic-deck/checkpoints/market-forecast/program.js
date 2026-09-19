/* doxagon-checkpoint-registration
{"schema": "doxagon.presentation-checkpoint/1", "id": "market-forecast", "version": "1.0.0",
 "assets": [], "capabilities": [], "forward_to": "probe-denied", "back_to": "market-base",
 "description": "Canvas drawing state; arbitrary rendering code, no reveal list."}
*/
export function create(context) {
  const canvas = context.root.querySelector('#forecast');
  const surface = canvas.getContext('2d');
  const bars = [40, 96, 64, 148, 120];
  return {
    enter() {
      surface.fillStyle = '#0f1f3d';
      surface.fillRect(0, 0, canvas.width, canvas.height);
      surface.fillStyle = '#4fd1c5';
      bars.forEach((height, index) => {
        surface.fillRect(24 + index * 56, canvas.height - height - 16, 40, height);
      });
      canvas.dataset.drawn = String(bars.length);
    },
    exit() {
      surface.clearRect(0, 0, canvas.width, canvas.height);
      delete canvas.dataset.drawn;
    },
    signature() {
      const pixels = surface.getImageData(0, 0, canvas.width, canvas.height).data;
      let hash = 2166136261;
      for (let index = 0; index < pixels.length; index += 997) {
        hash ^= pixels[index];
        hash = Math.imul(hash, 16777619) >>> 0;
      }
      return 'market-forecast:' + hash.toString(16).padStart(8, '0');
    },
    inspect() {
      return { bars: bars.length, drawn: canvas.dataset.drawn || null };
    },
  };
}
