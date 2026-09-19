/* doxagon-checkpoint-registration
{"schema": "doxagon.presentation-checkpoint/1", "id": "leaky-timer", "version": "1.0.0",
 "assets": [], "capabilities": ["timers"], "back_to": "probe-denied",
 "description": "Holds a granted brokered timer open across exit so closure fails."}
*/
export function create(context) {
  let handle = null;
  let ticks = 0;
  return {
    enter() {
      handle = context.capabilities.interval(() => { ticks += 1; }, 1000);
      context.root.dataset.entered = context.checkpointId;
    },
    exit() {
      /* Deliberately keeps the brokered handle: leaving a checkpoint must fail
         on the leak instead of continuing with shared mutable state. */
      delete context.root.dataset.entered;
    },
    signature() {
      return 'leaky-timer:' + (handle === null ? 'closed' : 'open');
    },
    inspect() {
      return { handle, ticks, open: context.capabilities.openHandles() };
    },
  };
}
