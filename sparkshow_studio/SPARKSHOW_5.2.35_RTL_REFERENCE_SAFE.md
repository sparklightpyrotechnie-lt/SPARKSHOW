# Sparkshow Studio 5.2.35 — RTL reference-safe variable-speed planner

This release bases RTL collision planning on the proven Lightshow Creator 3.15 trajectory model.

## RTL travel model
- Straight linear travel from the current position to the original launch position at RTL altitude.
- Cruise speed controls travel duration directly.
- Reposition/hold and normal vertical landing remain separate phases.
- Blender location F-curves for RTL travel are forced to LINEAR so the checked path is the executed path.

## Synchronized departure
- All drones start RTL on the same frame.
- Individual cruise speeds are selected from the configured maximum down to the configured minimum percentage.
- A candidate speed is accepted only when its complete timed RTL trajectory is clear of every previously accepted trajectory.
- Two deterministic search orders are attempted.
- When no safe common departure can be found inside the configured speed range, RTL stops with an explicit error instead of creating collisions.

## Non-synchronized departure
- The scheduler follows the proven reference algorithm: drones start at frame 0 when safe, otherwise the planner advances by `RTL frame interval` until the trajectory is safe.
- The exact reference checks are retained for both moving drones and drones that are still waiting on their launch pads.

## Important
The RTL acceleration setting is not used to curve the RTL path. This is intentional: the reference RTL model uses a constant-speed linear return, which makes collision verification deterministic.
