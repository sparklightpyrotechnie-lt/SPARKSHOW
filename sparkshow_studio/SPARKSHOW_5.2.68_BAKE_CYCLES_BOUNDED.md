# Sparkshow Studio 5.2.68
## Bake 2 Keyframes — cycles correctifs

- The 2-Keyframes/marker bake uses the complete user bake interval only.
- Keyframes can no longer be pushed outside the interval by the old temporal stagger.
- Every complete cycle repeats the same compact key pattern:
  - 2 stops: start/end;
  - N stops: start + intermediate markers + end.
- Non-final cycle ends are written one frame before the following cycle start, preserving the wrap instead of Blender deduplicating the two keys.
- Color evaluation still uses each drone's spatial factor and the existing preview/effect engine.
