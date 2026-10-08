Sparkshow Studio 5.2.50

Day Smoke bake uses volume-only material to remove the grey surface halo.

Sparkshow Studio 5.2.4

# Sparkshow Studio 5.0.0

Unified Blender 4.1 addon combining the validated Sparkshow Creator 4.1.17 workflow with the integrated Lighting/Palette engine.

## Architecture
- Show/formation/takeoff/landing/RTL/export: retained from Sparkshow 4.1.17 production branch.
- Lighting: integrated palette/gradient engine; targets Sparkshow drone objects only and writes through the existing Sparkshow color API.
- Pyro: retained procedural preview; objects stay exclusively in `Sparkshow Pyrotechnics` and are never inserted into drone family collections.
- Runtime: one shared frame-change handler coordinates Lighting and Pyro previews.

## RGBW
Lighting uses Sparkshow's existing four-channel Object.color representation for export compatibility. The Pyro engine has no access to those color properties. The Lighting detector never scans arbitrary emission materials, preventing Pyro materials from being treated as drone color targets.

## Installation
Remove/disable separate Sparkshow Creator and Palette installs before enabling Sparkshow Studio to avoid duplicated RNA properties or operator ids.


## Render safety (Blender 4.1)
Interactive Lighting/Pyro previews are viewport-only. During F12 or animation rendering, Sparkshow Studio temporarily removes live preview helpers and restores them after the render. The separate `Sparkshow Pyro Bake` collection remains renderable.


## Pyro Day Smoke dual render layer (5.2.22)

Day Smoke bake creates two isolated layers in `Sparkshow Pyro Bake`: a lightweight viewport surface cloud (`*_VIEWPORT`, never rendered) and a render-only procedural volume (`*_RENDER`, never shown in the viewport). Both use the same simulation attributes and follow the triggering drone with Copy Transforms; neither object is linked to drone Family collections.


5.2.44 fixes:
- authoritative show drone detection (avoids helper meshes being counted as drones);
- Live Preview frame handler registration;
- Solid viewport automatically uses Object.color during Live Preview;
- Live Preview is suspended during Bake.


5.2.44 fixes:
- Lighting/Palette now restores the V3 working preview+bake behavior while using Sparkshow's per-drone Object.color backend.
- Repairs the shared RGBW material if older scenes are missing the Object Info Color -> RGBW Emission link.
- Forces a dependency-graph refresh after preview updates.
- Lighting bake writes Object.color keyframes per drone and never edits the shared material socket.


5.2.50 fixes:
- Render intensity is explicitly simulation-only.
- It never changes RGBW color keyframes or exported show color events.
- New RGBW emission materials use a fixed shader baseline; the simulation intensity is applied only by the render/viewport settings callback.


## Render intensity
The Lighting/Color intensity control is Blender-simulation-only. It changes only the RGBW Emission shader Strength used for viewport/render visualization. RGBW color keyframes and exported show color events are not modified by this control.
