# Memory

> Chronological action log. Hooks and AI append to this file automatically.
> Old sessions are consolidated by the daemon weekly.

| 11:16 | Anonymous-user pixel-value interpretation popup: click a Displacement/Velocity pixel or select an address-search result that lands on one → popup with the real sampled value + plain-language subsidence interpretation (gated to `!isAuthed`). Confirmed via gdalinfo that OPERA DISP COGs are UTM (EPSG:326xx/327xx), not 4326 — pixelSample.js reprojects via proj4 using the zone derived from the EPSG code. Verified sampling math against 4 known pixels via local GDAL ground truth (exact match) using a Range-request-capable local server (python http.server does NOT support Range and silently corrupts geotiff.js reads — use `http-server`/nginx/real hosting for any future COG-sampling test). | ui/src/lib/pixelSample.js (new), ui/src/lib/layerContext.js (new, extracted from SubsideAnalysis.jsx), ui/src/components/mapworkbench/StacCogLayer.jsx, ui/src/components/mapworkbench/StacResults.jsx, ui/src/components/mapworkbench/AddressSearch.jsx, ui/src/components/mapworkbench/ModelMap.jsx, ui/package.json (+proj4 direct dep) | lint+build pass, sampling math verified against GDAL ground truth | ~180k |
| 12:15 | Bug fix (bug-001): user saw the full run-metadata popup (acquisition window, location, OPERA products, frame, run ID, layer range, bbox, button) plus the new interpretation block for anonymous users — wanted ONLY value + rate explanation. Replaced the append-on-top approach with an early `!isAuthed` branch in RunDetailsPopup rendering a separate minimal PixelValuePopup; authed view unchanged. Removed now-unused `.stac-run-popup-interpret` CSS. | ui/src/components/mapworkbench/StacResults.jsx, ui/src/styles.css | lint+build pass | ~15k |

## Session: 2026-07-27 12:34

| Time | Action | File(s) | Outcome | ~Tokens |
|------|--------|---------|---------|--------|
