# Sparkshow Studio 5.2.67 — Bake Cycles Fix

## Lighting / compact bake

- Honors the per-drone temporal window when evaluating effect progress.
- Multi-stop gradient marker keys repeat correctly for each temporal cycle.
- Integer cycle boundaries are explicitly anchored for WAVE/ROTARY when cycles > 1, preventing a single cycle from being stretched across the full bake interval.
- Keeps the compact 2-key / marker-based bake architecture and existing spatial stagger.
