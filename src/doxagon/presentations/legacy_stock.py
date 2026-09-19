"""Canonical producer for legacy stock choreography documents.

The migration recognizer accepts only the script emitted here after substituting
its motion table and step count. Keeping this producer separate from migration
makes the legacy byte contract independently verifiable.
"""

from __future__ import annotations

import json
from collections.abc import Mapping

LEGACY_STOCK_CHOREOGRAPHY_VERSION = 1

#: The producers' own step ceiling, and therefore the recognizer's: bytes that
#: claim more steps than this were not written here, so they are not canonical
#: and migration reports the slide instead of guessing at it. It sits below
#: `contracts.MAX_CHECKPOINTS`, so a deck this admits always fits the store.
MAX_LEGACY_STEPS = 1000

STOCK_CHOREOGRAPHY_SCRIPT = """var MOTION = __DOXAGON_MOTION__;
var STEPS = __DOXAGON_STEPS__;
function applyStep(n) {
  document.body.dataset.step = String(n);
  document.querySelectorAll('[data-enter]').forEach(function(el) {
    var entered = n >= Number(el.dataset.enter);
    el.classList.toggle('on', entered);
    el.classList.toggle('off', !entered);
  });
  document.querySelectorAll('[data-exit]').forEach(function(el) {
    var exited = n >= Number(el.dataset.exit);
    el.classList.toggle('on', !exited);
    el.classList.toggle('off', exited);
  });
  document.querySelectorAll('.plate:not([data-enter])').forEach(function(el) {
    el.style.transform = MOTION[n] || '';
  });
}
if (window.dox && dox.slide) {
  dox.slide.steps(STEPS);
  for (var s = 0; s < STEPS; s += 1) {
    dox.slide.onStep(s, function(step) {
      return function() { applyStep(step); };
    }(s));
  }
}
applyStep(0);"""


def render_stock_choreography(document: str, *, steps: int, motion: Mapping[str, str]) -> str:
    """Emit the versioned legacy script into one standalone HTML fragment."""

    if not 1 <= steps <= MAX_LEGACY_STEPS:
        raise ValueError(f"steps must be between 1 and {MAX_LEGACY_STEPS}")
    if not all(isinstance(key, str) and isinstance(value, str) for key, value in motion.items()):
        raise ValueError("motion must map strings to strings")
    script = STOCK_CHOREOGRAPHY_SCRIPT.replace(
        "__DOXAGON_MOTION__", json.dumps(dict(motion), separators=(",", ":"))
    ).replace("__DOXAGON_STEPS__", str(steps))
    return f"{document}<script>{script}</script>"


#: The second legacy producer, and the only one any real deck contains: the
#: per-project `tools/build_html_slides.py` writes this script, indented inside
#: an IIFE, with an unquoted-integer motion map that is not JSON.
#:
#: It is a different choreography from the one above, not a restyling of it. An
#: element before its enter step gets *neither* class here (the CSS base state
#: hides it), `data-exit` is read inside the same pass rather than overriding a
#: later one, and a step the motion map omits leaves the previous transform in
#: place instead of clearing it.
LEGACY_BUILDER_CHOREOGRAPHY_VERSION = 1

BUILDER_CHOREOGRAPHY_SCRIPT = "\n(function () {\n  var MOTION = __DOXAGON_MOTION__;\n  var STEPS = __DOXAGON_STEPS__;\n  function applyStep(n) {\n    document.body.dataset.step = n;\n    document.querySelectorAll('[data-enter]').forEach(function (el) {\n      var a = +el.dataset.enter;\n      var b = el.dataset.exit ? +el.dataset.exit : Infinity;\n      el.classList.toggle('on', n >= a && n < b);\n      el.classList.toggle('off', n >= b);\n    });\n    var plates = document.querySelectorAll('.plate');\n    plates.forEach(function (p) {\n      if (!p.dataset.enter && MOTION[n]) p.style.transform = MOTION[n];\n    });\n  }\n  if (window.dox && dox.slide) {\n    dox.slide.steps(STEPS);\n    for (var i = 0; i < STEPS; i++) {\n      (function (s) { dox.slide.onStep(s, function () { applyStep(s); }); })(i);\n    }\n  }\n  applyStep(0);\n})();\n"


def builder_motion_literal(motion: Mapping[int, str]) -> str:
    """The builder's motion map exactly as it writes it: integer keys, no JSON."""

    return "{ " + ", ".join(f'{key}: "{value}"' for key, value in motion.items()) + " }"


def render_builder_choreography(document: str, *, steps: int, motion: Mapping[int, str]) -> str:
    """Emit the versioned builder script into one standalone HTML fragment."""

    if not 1 <= steps <= MAX_LEGACY_STEPS:
        raise ValueError(f"steps must be between 1 and {MAX_LEGACY_STEPS}")
    if not all(isinstance(key, int) and isinstance(value, str) for key, value in motion.items()):
        raise ValueError("motion must map integers to strings")
    script = BUILDER_CHOREOGRAPHY_SCRIPT.replace(
        "__DOXAGON_MOTION__", builder_motion_literal(motion)
    ).replace("__DOXAGON_STEPS__", str(steps))
    return f"{document}<script>{script}</script>\n"
