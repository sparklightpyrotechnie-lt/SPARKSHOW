# Sparkshow Studio 5.2.30 — RTL synchronized safe departure

## Correction

5.2.29 allowed the first RTL wave to ignore drones that were still occupying
their takeoff pads. That can create real collisions when a route passes close
to the pad of a drone that is delayed to a later frame.

5.2.30 restores the takeoff-pad safety test for the first RTL slot. The
scheduler still evaluates the complete pending set at the same frame, so
independent drones can leave simultaneously. A departure is delayed only when
its planned route conflicts either with an already accepted trajectory or with
a drone that must remain on its takeoff pad.

The acceleration/deceleration profile, pre-landing hold and time-aware
trajectory collision checks are unchanged.
