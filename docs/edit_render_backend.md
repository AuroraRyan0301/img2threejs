# Editing capture backend: original browser Three.js

Use the original browser runtime, capture API, profile schema, six-channel bridge
and mesh export described in `grimoire/build/python_threejs_render_bridge.md` and
`grimoire/feedback/render_capture.md`. This document changes no upstream capture
requirements. Do not use Blender or an offline rasterizer. Build an actual usable
runtime before the first constructed turn. A failed browser is an environment
failure, not evidence that a visual gate passed.

Capture genuine depth and normals, not constant-color stand-ins. Semantic IDs
need a stable explicit region mapping; material-ID and roughness encodings must
be declared accurately. Preserve the original checks and record missing evidence.

The source-editing baseline differs from reconstruction: use the current model
for preservation, target RGB for the requested change. Do not load hidden GT
passes. Return to the supplied evaluation camera and verify its projection and
units (including any distance normalization); diagnostic cameras remain editable.
