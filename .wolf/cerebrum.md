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

## Do-Not-Repeat

<!-- Mistakes made and corrected. Each entry prevents the same mistake recurring. -->
<!-- Format: [YYYY-MM-DD] Description of what went wrong and what to do instead. -->
- [2026-07-27] Added a static `import parseGeoraster from 'georaster'` to a new lib module (pixelSample.js) and only caught the ~580KB main-bundle regression by reading `npm run build`'s chunk-size output afterward. Always check the build's chunk sizes after touching any file that imports `georaster` (or other large lazy-loaded libs) — don't assume an import in a "shared lib" file is free of bundling side effects.

## Decision Log

<!-- Significant technical decisions with rationale. Why X was chosen over Y. -->

- [2026-07-27] Displacement runs now always render via the real COG (StacCogLayer), matching velocity — dropped the "prefer the cheap PNG overlay when available" behavior. I flagged the tradeoff first (overlay is near-zero client cost for up to 24 simultaneous runs; the overlay PNG is also a 2nd–98th-percentile-clipped viridis rendering per analysis/h2i_lab/preview.py, not an invertible encoding of the real value) but the user explicitly chose accuracy/consistency over that render-cost saving ("Render the Cogs"). The PNG overlay is now only a fallback for the rare run with no COG asset published at all — those still can't be pixel-sampled (no COG to read). Removed `sampleCogValueAt`/the lazy-COG-read-for-overlay code path from pixelSample.js as dead code once this landed.
