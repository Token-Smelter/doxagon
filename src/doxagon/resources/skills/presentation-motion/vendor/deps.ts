// The whole Three namespace, so scenes never need workarounds for a missing export.
export * from './three.module.js';
export { RoomEnvironment } from './three-addons/environments/RoomEnvironment.js';
export { RoundedBoxGeometry } from './three-addons/geometries/RoundedBoxGeometry.js';
export { LineSegments2 } from './three-addons/lines/LineSegments2.js';
export { LineSegmentsGeometry } from './three-addons/lines/LineSegmentsGeometry.js';
export { LineMaterial } from './three-addons/lines/LineMaterial.js';
export { createThreeAdapter } from './hyperframes/packages/core/src/runtime/adapters/three';
export { forceDispatchSeekEvent, waitForSeekCompletion } from './hyperframes/packages/core/src/runtime/adapters/seek-dispatch';
export { getFragSource } from './hyperframes/packages/shader-transitions/src/shaders/registry';
export { NQ } from './hyperframes/packages/shader-transitions/src/shaders/common';
