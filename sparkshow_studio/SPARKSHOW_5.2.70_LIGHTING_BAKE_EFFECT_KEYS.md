# Sparkshow Studio 5.2.70 — Lighting Bake Effect Keys

## Purpose
Correct compact 2-key/marker bake colors so the baked animation follows the same temporal law as the Lighting preview.

## Fixes
- WAVE / ROTARY marker crossings use the drone spatial factor when computing their timing.
- PULSE uses the same `cycles * speed` frequency as the preview.
- PULSE marker crossings account for the smoothstep and pulse minimum intensity.
- PULSE includes actual extrema so a 2-color gradient can still show repeated pulses with a compact bake.
- Scanner / KITT marker crossings follow their triangle-wave timing.
- No change to the show/export RGBW data model.
