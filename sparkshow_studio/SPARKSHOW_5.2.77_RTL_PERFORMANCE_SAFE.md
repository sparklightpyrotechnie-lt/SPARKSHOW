# Sparkshow Studio 5.2.77 — RTL performance / hard-crash protection

- Optimized synchronized RTL collision checks with a direct exact piecewise-linear distance solver.
- Added trajectory AABB broad-phase pruning.
- Cached synchronized trajectories between repair iterations and candidate checks.
- Solver now stops at the first collision instead of building and sorting the entire collision list on every pass.
- Added progress messages every 50 repair passes.
- Kept existing motion profile, acceleration limit, variable-speed synchronized departure, and asynchronous Lightshow Creator reference scheduler.
- No Lighting / Gradient changes in this release.
