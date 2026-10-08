# Sparkshow Studio 5.2.29 — RTL synchronized departure

## RTL behavior

- The first RTL slot is a synchronized departure wave: every drone is allowed to attempt departure on the same frame.
- The scheduler does not reject a first-wave departure merely because the route passes near another drone's still-occupied launch pad.
- Real trajectory conflicts are still checked with the time-aware minimum-distance solver. A drone is delayed only when its actual planned trajectory conflicts with a trajectory already accepted for the same/previous wave.
- After the first wave, the launch-pad safety check remains active for drones that are still waiting on their original takeoff pads.
- Acceleration/deceleration limits and the explicit pre-landing hold remain unchanged.

## Goal

Minimize the number of delayed RTL departures and keep the return/landing phase as parallel as the geometry and minimum-distance constraint allow.
