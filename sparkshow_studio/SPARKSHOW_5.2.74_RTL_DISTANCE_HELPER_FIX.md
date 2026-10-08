# Sparkshow Studio 5.2.74 — RTL Distance Helper Fix

## RTL solver
- Restored the missing `_trajectory_min_distance_squared()` helper used by the synchronized RTL collision solver.
- The helper delegates to the existing asynchronous trajectory distance engine so timed clearance uses the same segment model throughout the RTL solver.
- Degenerate or empty trajectory comparisons return `+inf` instead of raising from an empty `min()` sequence.

## Compatibility
- Keeps the 5.2.73 take-off family spacing changes and all other existing features unchanged.
