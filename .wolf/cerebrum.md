# Cerebrum

> OpenWolf's learning memory. Updated automatically as the AI learns from interactions.
> Do not edit manually unless correcting an error.
> Last updated: 2026-07-23

## User Preferences

<!-- How the user likes things done. Code style, tools, patterns, communication. -->

- [2026-07-27] For anonymous/gated UI states, show ONLY the minimum content the request describes — don't append new content onto an existing richer view "just in case." When a feature is scoped to a specific user state (e.g. `!isAuthed`), give that state its own minimal render path rather than layering new content on top of the full/default view. Corrected after the pixel-value popup initially showed full run metadata + the new interpretation block for anonymous users, when the user wanted just the value + a short explanation.

## Key Learnings

- **Project:** subside
- **Description:** **Subsidence System for Insight and Data Exploration** — a statewide portal that
- **ui/**: most Displacement runs render via a cheap pre-rendered PNG `ImageOverlay` (STAC asset key `overlay`), not the streamed COG (`StacCogLayer`) — but `itemLayers(item)` (ui/src/lib/stacApi.js) still returns the real `cog` asset alongside the `overlay` one, so per-pixel sampling for an overlay-rendered run is possible by lazily parsing just that COG on demand (see `sampleCogValueAt` in ui/src/lib/pixelSample.js), not by re-rendering it as a layer.
- **ui/**: `georaster` (~580KB) MUST be imported via `import('georaster')` (dynamic), never a static top-level `import ... from 'georaster'` — a static import anywhere in the module graph pulls the whole bundle out of its lazy chunk into the main bundle. `npm run build`'s chunk-size output is the way to catch this; StacCogLayer.jsx's existing `loadGeoraster` already does this correctly — match that pattern in any new module that needs georaster.
- **ui/styles.css**: the generic `.slp-row .slp-name` rule (`.slp-name` truncated to one line inside any `.slp-row`) has specificity (0,2,0). A new single-class rule like `.slp-run-name { white-space: normal }` will NOT override it regardless of source order. To override truncation for a specific row variant, match the ancestor-combinator shape, e.g. `.slp-run-row .slp-name` (also 0,2,0, so it wins by being later in the file).
- **ui/ — critical**: `georaster-layer-for-leaflet@4.1.2` (verified against BOTH dist entry points package.json actually resolves — `main` and `module` — not just one bundle) has NO click/interactive-target support whatsoever: it's a plain `L.GridLayer.extend({...})` that never calls `addInteractiveTarget` and never fires `'click'`/`'contextmenu'` on the layer. `layer.on('click', ...)` on a `GeoRasterLayer` instance (as StacCogLayer.jsx used to do) is a silent no-op — it never throws, it just never fires. Real interactivity for a StacCogLayer-rendered pixel MUST be done at the map level (`useMapEvents({click, contextmenu})` in the parent), checking the click's lat/lon against each layer's own `getBounds()` + a point-sampler (see `findSampledRunAt` in StacResults.jsx). Don't add `layer.on(...)` calls to StacCogLayer expecting them to fire.
- **ui/**: `GeoRasterLayer`'s `resampleMethod` option only controls the FIRST of two internal resample stages (georaster-stack reading/reprojecting into `tileRasters`, per georaster-layer-for-leaflet.js's own comment "this is separate from the resampleMethod that does the actual reprojection"). The final canvas-draw step that calls `pixelValuesToColorFn` is hardcoded to `method: "near"` internally — but since that stage just copies whatever the first stage already computed, setting `resampleMethod: 'bilinear'` (added to StacCogLayer.jsx) still visibly smooths tiles; it isn't overridden back to nearest.
- **ui/ — data**: SUBSIDE's displacement/velocity COGs use literal IEEE `NaN` as their nodata sentinel (confirmed via `gdalinfo`'s `noDataValue` field on a real local COG — not a numeric fill like -9999). This is why `bilinear` resampling is safe here: NaN excluded from geowarp's interpolation weighting (verified with a standalone geowarp test) rather than producing garbage blended colors at data-gap edges. If a future raster uses a numeric nodata sentinel instead, re-verify this before assuming bilinear is still safe.
- **ui/ — bug pattern**: `combinedRange()` in StacResults.jsx (the min/max across ALL currently-shown runs of a kind) was computed and shown in the panel's `RasterLegend`, but each individual `StacCogLayer` was colored using its OWN per-run `range` instead — meaning the legend didn't match what was actually rendered, and side-by-side runs weren't color-comparable. Watch for this pattern generally: a "combined/summary" value computed for display (a legend, a header stat) silently NOT being the same value actually driving the thing it's summarizing.

## Do-Not-Repeat

<!-- Mistakes made and corrected. Each entry prevents the same mistake recurring. -->
<!-- Format: [YYYY-MM-DD] Description of what went wrong and what to do instead. -->
- [2026-07-27] Added a static `import parseGeoraster from 'georaster'` to a new lib module (pixelSample.js) and only caught the ~580KB main-bundle regression by reading `npm run build`'s chunk-size output afterward. Always check the build's chunk sizes after touching any file that imports `georaster` (or other large lazy-loaded libs) — don't assume an import in a "shared lib" file is free of bundling side effects.
- [2026-07-27] Shipped `layer.on('click', ...)` on a `GeoRasterLayer` (StacCogLayer.jsx) across multiple rounds of edits — including bug-002's fix — without ever confirming it fires from a REAL browser click; only verified the sampling math via Node scripts calling the sampler function directly. It never fired (see the georaster-layer-for-leaflet Key Learning above); the bug was invisible because displacement mostly rendered via ImageOverlay (which does work) until "Render the Cogs" made StacCogLayer universal. For any Leaflet-layer click/interactivity claim, verify with an actual browser click (Playwright or manual) before considering it done — a passing sampling-logic test is NOT evidence the click event itself fires.

## Decision Log

<!-- Significant technical decisions with rationale. Why X was chosen over Y. -->

- [2026-07-27] Displacement runs now always render via the real COG (StacCogLayer), matching velocity — dropped the "prefer the cheap PNG overlay when available" behavior. I flagged the tradeoff first (overlay is near-zero client cost for up to 24 simultaneous runs; the overlay PNG is also a 2nd–98th-percentile-clipped viridis rendering per analysis/h2i_lab/preview.py, not an invertible encoding of the real value) but the user explicitly chose accuracy/consistency over that render-cost saving ("Render the Cogs"). The PNG overlay is now only a fallback for the rare run with no COG asset published at all — those still can't be pixel-sampled (no COG to read). Removed `sampleCogValueAt`/the lazy-COG-read-for-overlay code path from pixelSample.js as dead code once this landed.
