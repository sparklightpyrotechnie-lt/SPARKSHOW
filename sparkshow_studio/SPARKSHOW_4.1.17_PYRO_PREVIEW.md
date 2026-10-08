# Sparkshow Studio 4.1.17 — Pyrotechnic preview

The Fire keyframe/export system is unchanged.

Pyrotechnic preview objects are isolated in the top-level `Sparkshow Pyrotechnics`
collection. They are never linked to drone-family collections and are never
parented to drones. On every frame, their `matrix_world` follows the evaluated
world matrix of the firing drone.

The preview is intentionally implemented with standard Blender Curve and Mesh
data instead of relying on Geometry Nodes evaluation. Sparks use ballistic
trajectories with gravity, emission delay, trails and twinkle. Day smoke uses
multiple irregular low-poly puffs with rising motion, horizontal expansion,
turbulence and opacity dissipation.

Fire channels remain independently assignable to Pyro 1, Pyro 2 or Pyro 3.


## Pyro 4.1.17
- Fountain diffusion axis with default local Z-.
- Separate initial projection speed and trail length.
- Smoke material uses Blender 4.1 alpha blending with procedural noise.
- Smoke mesh definition control (6-24 segments).
- Pyrotechnic preview remains isolated in `Sparkshow Pyrotechnics`.
