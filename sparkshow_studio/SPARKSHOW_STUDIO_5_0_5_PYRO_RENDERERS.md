# Sparkshow Studio 5.0.6 — Pyro Renderers

Renderer fixes:
- GPU Points now use a self-contained Blender 4.1 point shader with soft alpha falloff.
- Instanced Mesh preview is displayed as solid geometry instead of wireframe and keeps its emission material.
- Particle Emitters use `event.drone_name` consistently.
- All preview engines remain isolated in `Sparkshow Pyrotechnics`.
