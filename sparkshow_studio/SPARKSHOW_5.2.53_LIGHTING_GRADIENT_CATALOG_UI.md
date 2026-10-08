# Sparkshow Studio 5.2.54

## Lighting — Gradient Catalog

- Gradient previews now use a stable signature instead of `id(preset)`.
- The gradient preview collection is rebuilt automatically after opening/reloading a `.blend`.
- A missing runtime preview is rebuilt lazily from the stored gradient stops, so the preview no longer depends on clicking the preset name first.
- Gradient catalog entries are displayed compactly with the preview and name on the same UI line.
- The list shows up to six compact rows instead of four tall rows.
- Stored preview interpolation is tracked for deterministic thumbnail reconstruction.
- Existing Lighting, Preview, Bake, Pick Color and RTL functionality is otherwise unchanged.


### 5.2.54
- Ajout de réglages Taille et Largeur des aperçus du catalogue de dégradés.
