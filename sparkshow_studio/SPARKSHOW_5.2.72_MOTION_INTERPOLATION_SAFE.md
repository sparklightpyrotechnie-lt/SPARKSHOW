# Sparkshow Studio 5.2.72 — Motion interpolation and physical profile

## Motion
- Go to target constraint influence uses exact cubic smoothstep endpoint tangents.
- Direct Take Off no longer inserts a handful of extra keys near the end; each semantic segment is a bounded smooth cubic.
- Landing vertical segments use the same zero-velocity cubic at their boundaries.
- RTL cruise uses the physical acceleration/deceleration profile restored from the proven 5.2.31 implementation; duration planning and the generated F-curves use the same profile model.
- Speed and acceleration checks therefore evaluate the same motion model that is generated.

## Safety
The motion profile is deterministic and uses the configured horizontal/vertical speed and acceleration limits. Re-test Speed & Acceleration after generation before export.
