# Sparkshow Studio 5.2.73 — Takeoff Family Spacing

Auto Take Off now delays each successive drone of the same family until the previous drone has physically cleared the configured minimum collision distance plus 10% margin, using the same smoothstep trajectory as the generated takeoff curves. One extra frame is added to avoid discrete-frame contact.
