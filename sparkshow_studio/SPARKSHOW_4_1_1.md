# Sparkshow Studio 4.1.1

Production-targeted replacement for Lightshow Creator 3.19.2 on Blender 4.1.

## Fixed in 4.1.1
- Restored RGBW keyframe consistency validation required by export and color tools.
- Unified object-color animation for regular and imported drones.
- Kept private emission materials for effectors/selected meshes.
- Shared drone mesh + shared RGBW material remain the scalable representation.
- Sidebar tab is `sparkshow`.

## Validation
- All Python modules compile successfully with Python 3.11+ syntax validation.
- Static runtime-relative-import validation reports zero missing local symbols.

Blender 4.1 runtime execution still needs to be validated on the target workstation because Blender itself is not available in this build environment.
