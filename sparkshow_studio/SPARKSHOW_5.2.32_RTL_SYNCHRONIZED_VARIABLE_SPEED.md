# Sparkshow Studio 5.2.32 — RTL synchronized departure with variable cruise speed

## RTL behavior

- All drones are first offered the same RTL start frame.
- The planner uses the configured RTL speed as the maximum cruise speed.
- When two trajectories conflict, the planner first changes the candidate drone cruise speed rather than delaying its departure.
- Cruise speed candidates are adaptive and descend only as needed, down to the configurable minimum percentage of the RTL speed.
- Acceleration and deceleration remain bounded by the show acceleration limit.
- With synchronized departure enabled, a start delay is NOT used: all drones share the exact same RTL start frame. If the allowed cruise-speed range cannot resolve the geometry safely, RTL reports the remaining conflict instead of staggering the launch.
- The planner now uses 25 discrete cruise-speed levels and a monotonic exploration step to escape some speed-assignment dead ends.
- Each drone receives its own selected cruise speed and duration.
- The existing pre-landing hold and normal landing animation are preserved.

## UI

`RTL minimum cruise speed` controls the lowest percentage of the configured RTL speed that may be used for synchronized collision avoidance.

`Synchronized departure` forces the whole fleet onto the same RTL start frame.

## Goal

Keep the RTL departure synchronized for the whole fleet whenever the configured speed range can safely resolve the geometry. Otherwise, synchronized mode stops instead of introducing staggered launches.

## Safety behavior

The synchronized mode never trades collision safety for a visual departure. When the available speed range is insufficient, the planner stops and reports that the geometry/settings must be changed.
