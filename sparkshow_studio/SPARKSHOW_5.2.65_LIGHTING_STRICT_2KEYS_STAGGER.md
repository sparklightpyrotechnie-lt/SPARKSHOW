# Sparkshow Studio 5.2.65 — Strict 2 Keyframes spatial stagger

- 2 Keyframes now creates exactly one start and one end color key per selected drone.
- The pair is shifted in time according to the drone spatial factor in the active gradient.
- Default offset span: 100% of the configured gradient duration.
- The pair keeps the same duration; the formation therefore produces staggered start/end windows.
- New Bake setting: “Décalage 2 Keyframes” (0 = no stagger, 1 = one full effect duration, max 3).
- Animated effects and fades are evaluated in each drone’s local two-key window.
- Existing Lighting color backends and JITTER key types are preserved.
