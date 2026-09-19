/* doxagon-checkpoint-registration
{"schema": "doxagon.presentation-checkpoint/1", "id": "probe-denied", "version": "1.0.0",
 "assets": [], "capabilities": ["timers"], "forward_to": "leaky-timer", "back_to": "market-forecast",
 "description": "Reaches ungranted host APIs, the host realm, the raw form of its own granted capability, the broker's own bindings, and the host reply channel; every one must refuse."}
*/
export function create(context) {
  const results = {};

  /* The names are assembled at run time on purpose. The static scanner reads
     tokens, so a computed name reaches the realm unflagged — which is the only
     way to prove the runtime denial is enforcement rather than a second copy of
     the same static rule. */
  const probe = (label, name) => {
    try {
      const api = window[name];
      if (typeof api !== 'function') {
        results[label] = 'absent';
        return;
      }
      api('/never-reached');
      results[label] = 'allowed';
    } catch (error) {
      results[label] = String(error && error.message).slice(0, 48);
    }
  };

  /* Name a binding the broker holds in its own module scope. If the broker and
     this entry ever share one scope again, the name resolves and the realm's
     raw APIs, handle registry, and host reference are author-reachable. */
  const reach = (label, read) => {
    try {
      const value = read();
      results[label] = value === undefined ? 'undefined' : 'reachable';
    } catch (error) {
      results[label] = 'unreachable';
    }
  };

  return {
    enter() {
      probe('network', 'fet' + 'ch');
      probe('storage', 'local' + 'Storage');
      probe('worker', 'Wor' + 'ker');
      /* This checkpoint IS granted timers, and the raw global must still
         refuse: a grant buys a tracked broker handle, never the host API. A
         raw granted handle would never appear in the closure account below. */
      probe('timers-raw', 'set' + 'Timeout');
      try {
        const handle = context.capabilities.timeout(() => {}, 5);
        results['timers-brokered'] = typeof handle === 'string' ? 'handle' : 'unexpected';
        results['timers-open'] = context.capabilities.openHandles().join(',');
        context.capabilities.release(handle);
        results['timers-closed'] = context.capabilities.openHandles().length === 0 ? 'closed' : 'open';
      } catch (error) {
        results['timers-brokered'] = String(error && error.message).slice(0, 48);
      }
      try {
        const foreign = window.parent.document.title;
        results['cross-realm'] = 'allowed:' + String(foreign).length;
      } catch (error) {
        results['cross-realm'] = 'refused';
      }
      /* Broker internals must not be lexically reachable from author code. */
      reach('broker-raw', () => __doxRaw);
      reach('broker-open', () => __doxOpen);
      reach('broker-host', () => __doxHost);
      reach('broker-broker', () => __doxBroker);
      reach('broker-registrar', () => window.__doxagonRegisterCheckpoint);
      /* Reply forgery: answer the host as if this checkpoint were the broker.
         Replies travel over a private port, so a window message to the host
         names no request and settles nothing. If the host ever adopted one,
         the signature it reports for this checkpoint would be the forged one
         below rather than the one signature() computes. */
      try {
        for (let id = 1; id <= 8; id += 1) {
          window.parent.postMessage({ id: id, ok: true, signature: 'forged-signature', leaked: [] }, '*');
        }
        results['reply-forgery'] = 'sent';
      } catch (error) {
        results['reply-forgery'] = 'refused';
      }
      context.root.querySelector('#probe-output').textContent = Object.keys(results).sort().join(' ');
      context.root.dataset.entered = context.checkpointId;
    },
    exit() {
      context.root.querySelector('#probe-output').textContent = '';
      delete context.root.dataset.entered;
    },
    signature() {
      const denied = Object.keys(results).filter((key) => results[key] !== 'allowed').sort();
      return 'probe-denied:' + denied.join(',');
    },
    inspect() {
      return { ...results };
    },
  };
}
