# Sparkshow Studio 5.2.69 — Bake 2 Keyframes bounded spatial stagger

- Restores the requested spatial temporal stagger for compact gradient bakes.
- Every drone keeps the same effect duration; its local start/end window is shifted by its spatial factor.
- The maximum stagger is automatically clamped to the free space available inside Blender's scene render range.
- All generated keys, including intermediate gradient markers and repeated cycle markers, stay inside the render range.
- Cycle count remains evaluated inside each drone's shifted local window, so multiple cycles are not stretched or collapsed.
- The F-curve writer range now covers the full shifted interval.
- No changes to UNI, adaptive/frame-by-frame bake, Preview, Pick Color, or RTL logic.
