"""Runtime bytes loaded by every presentation surface.

`runtime.js` is the one checkpoint runtime; `offline-shell.js` is the export
document's shell over it. They are data, not an importable module, so nothing
here re-exports them: `doxagon.presentations.runtime` is the only reader.
"""
