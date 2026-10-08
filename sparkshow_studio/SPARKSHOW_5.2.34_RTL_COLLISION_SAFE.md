# Sparkshow Studio 5.2.34 — RTL synchronized variable-speed collision-safe interpolation

This revision keeps the RTL planner and the Blender animation on the exact same geometric trajectory.

## Safety correction

- RTL travel keyframes are now forced to `LINEAR` interpolation for the calculated travel interval.
- The collision solver also uses piecewise-linear trajectory segments, so the path it checks is the path Blender follows.
- The previous custom Bezier tangent generation was removed from RTL travel because Bezier overshoot could create a real collision after a trajectory had passed the analytical planner.
- Cruise-speed variation is preserved: different drones can still use different travel durations/speeds while leaving on the same frame.

## Modes

- `Synchronized departure` enabled: common RTL start frame; speeds are varied first; unresolved conflicts stop the operation instead of producing unsafe trajectories.
- `Synchronized departure` disabled: legacy delayed-start scheduling; configured RTL speed is retained; conflicting drones are shifted in time.

## Blender 4.1

The package remains compatible with Blender 4.1.
