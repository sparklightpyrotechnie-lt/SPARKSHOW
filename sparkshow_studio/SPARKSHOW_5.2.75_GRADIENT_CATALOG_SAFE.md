# Sparkshow Studio 5.2.76 — Gradient catalog safe rebuild

- Removed the immediate gradient catalog rebuild from addon registration.
- Deferred catalog rebuild until after Blender finishes loading via bpy.app.timers.
- Reworked gradient thumbnails to write PNGs directly with Python stdlib instead of bpy.data.images/Image.pixels.
- UI draw no longer creates/mutates Blender Image datablocks when a thumbnail is missing.
- Preview width changes now defer thumbnail regeneration.
- No RTL or motion logic changed in this version.
