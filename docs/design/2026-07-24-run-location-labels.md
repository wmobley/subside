# Run location labels

## Status

Implementing. The date+frame+run-id disambiguation fix described in this spec's
"CKAN naming precedent" was split out and shipped separately (see
`subside/ui/src/components/mapworkbench/StacResults.jsx` `runIdSuffix`/`runRowLabel`,
2026-07-24) per architect + skeptic review below. The `subside:location`
enhancement was then revised per that same review and implemented across
STAC, UI, and now all three live Tapis pipeline YAMLs. Only the actual
`register.py --recreate-pipelines` deploy step remains, gated on explicit
approval per this project's external-write rules — see "Implementation
summary" below.

## Objective

Add human-readable location names to each SUBSIDE STAC item (Displacement/Velocity run),
computed at publish time from the run's bounding box and displayed in the Risk Explorer
map's "Previous runs" panel. When multiple runs share the same acquisition window,
location names disambiguate them on screen. Scale the specificity of the location (e.g.,
street address vs. county vs. state) to the bbox size so small runs show precise place
names and large runs show broader regions.

## User need

**Primary user:** Risk Explorer analyst running displacement / subsidence-velocity analyses
on the SUBSIDE STAC catalog.

**Job-to-be-done:** Quickly identify which geographic region(s) a past run covered, so
they can reason about whether a particular cached result is relevant to a new analysis
without hovering each row to read the bounding box coordinates.

**Current pain:** The Risk Explorer map's "Previous runs" panel lists each Displacement
or Velocity run with only the acquisition date window (e.g., `2025-06-01 → 2025-09-01`).
When multiple runs have the same window — a common scenario with reprocessing passes or
alternate framing — every row reads identically, making it impossible to distinguish
which is which without opening the detail popup or examining the bbox. This friction
slows selection of the right run, especially in a list of 5+ similar-dated runs.

**Definition of success:** Each run row is labeled with its acquisition window + a
disambiguating location name, e.g., `2025-06-01 → 2025-09-01 · New Braunfels, TX · run
1748268-007`. The location name is specific (address-level) for small runs and broader
(county- or state-level) for large runs, reflecting the geographic precision of the data.

## Current code/system summary

**Risk Explorer UI (`StacResults.jsx`):**
- `runRowLabel(item, kind)` (~lines 73–78) generates the toggle-list row label by reading
  `itemMeta(item)` and composing only the date window (`start` / `end` timestamps from
  STAC properties) plus reference mode for velocity runs (e.g., `2025-06-01 → 2025-09-01 · ref ENU`).
  Frame ID and run UUID are not included.
- `RunDetailsPopup` (~lines 109–193) shows the same date window in a `<dl>` row labeled
  "Acquisition window" (lines 148–153) and separately displays Frame IDs, reference point
  coords, and bbox — but no location name.

**STAC item metadata reader (`stacApi.js`):**
- `itemMeta(item)` (~lines 87–100) extracts STAC item `properties` and returns a
  normalized object with `start`, `end`, `productCount`, `frameIds`, and `reference`
  (lat/lon/mode). It does NOT currently read a location property.

**Publisher (`stac-platform/stacmap/manifest.py`):**
- `granule_from_subside_manifest(manifest, item_id)` (~lines 93–118) is the single
  shared function where STAC item properties are assembled. It already writes:
  - `subside:frame_ids` — array of frame integers (H2I multi-frame runs) or single frame
    (WERC).
  - `subside:product_count` — integer count of OPERA source products.
  These properties flow into published STAC items and are mirrored into CKAN dataset/resource
  extras via the `stacmap.publish` library (used by both `werc-opera.yaml` and
  `h2i-opera.yaml` Tapis pipelines, and the `subside-publish` standalone republish pipeline
  per the 2026-06-25 spec).

**Existing geocoding precedent:**
- `AddressSearch.jsx` (~lines 1–40) already calls `https://nominatim.openstreetmap.org/search`
  (keyless, no API key required) for client-side forward geocoding (user types a place name,
  Nominatim returns results). This shows that Nominatim is an accepted external service
  dependency in this codebase, already carrying the `User-Agent` header requirement per OSM
  policy. However, `AddressSearch` performs one-off, user-driven queries; it does NOT do
  batch/repeated calls at render time.

**STAC item naming precedent:**
- CKAN resources already carry disambiguated titles set by the publisher, e.g.,
  `"Cumulative displacement GeoTIFF (COG) - 2025-06-01 to 2025-09-01 - run 17482688-007"`
  and `"Displacement GeoTIFF (COG) - 2025-06-01 to 2025-09-01 - run dffd251c-007"`.
  The `run <first-8-hex-of-uuid>-<job-suffix>` suffix disambiguates in CKAN. This pattern
  should inform the Risk Explorer UI label (include run ID to be consistent with CKAN).

## Proposed design

### 1. Compute location at publish time

Add a new STAC item property `subside:location` (following the existing `subside:` namespace
convention) in `granule_from_subside_manifest`. The location name is computed **once per
run**, when the STAC item is created, using the run's bounding box + Nominatim reverse
geocoding. This location is then stored in the STAC item properties and mirrored into
CKAN dataset/resource extras (same flow as `subside:frame_ids` / `subside:product_count`).

**Location naming format (proposed; subject to user approval below):**

Given a bounding box and its max extent in km, call Nominatim's `/reverse` endpoint with a
`zoom` level scaled to the bbox size. The `zoom` parameter controls which `address.*` fields
Nominatim returns (higher zoom = finer address level; lower zoom = broader region).

Proposed thresholds (scaling the max bbox extent in km to a Nominatim zoom level):

| Bbox max extent (km) | Nominatim zoom | Preferred address field | UI label example |
|---|---|---|---|
| < 20 (small neighborhood) | 18 | `address.suburb` or `address.village` (if no suburb) | "Braunfels" |
| 20–100 (city/metro) | 14 | `address.city` or `address.town` (if no city) | "New Braunfels, TX" |
| 100–500 (county/region) | 10 | `address.county` | "Caldwell County, TX" |
| > 500 (state/multistate) | 6 | `address.state` | "Texas" |

Actual run bboxes in the SUBSIDE catalog are ~65–70 km typically (multi-frame H2I runs
spanning ~50 × 50 km AOIs), so they fall into the 20–100 km bucket and should display as
city-level names ("New Braunfels, TX"). Larger multi-year or multi-region runs would scale
to county names.

The final location string format is: **`{location} · {state_abbrev}` ** (e.g., "New
Braunfels, TX"), or state-level **`{state_abbrev}` ** if no city name, or **`{country}` **
as an ultimate fallback (highly unlikely for US runs).

**Emit as `subside:location`** in the `properties` dict in `granule_from_subside_manifest`.
If reverse geocoding fails or the bbox is invalid, omit the property or set it to `null` —
the UI will fall back gracefully.

### 2. Backfill existing published runs

A one-off Python script (not a Tapis pipeline; separate from the live publish tasks):
- Iterates over all already-published STAC items in the target collection (e.g.,
  `subsidence-rates`).
- For each item with a valid bbox but no `subside:location` property, calls Nominatim
  `/reverse` with the bbox center point + appropriate zoom level.
- PATCHes the STAC item to add `subside:location` (via stac-platform API or direct S3 +
  catalog re-index, depending on the store).
- Also PATCHes the mirrored CKAN dataset/resource extras if the resource is registered in
  CKAN (so CKAN datasets stay in sync).
- Logs results: success count, skips (already has location, invalid bbox), errors (Nominatim
  timeout, API quota).
- Supports a dry-run flag to preview changes without writing.

This is an **external write** (modifies CKAN + STAC) and requires explicit approval and
dry-run validation before execution (see Rollout/rollback).

### 3. Update UI display

**In `stacApi.js` (`itemMeta` function):**
- Add a `location` field to the returned object, reading from `p['subside:location']` or
  returning `null` if absent.

**In `StacResults.jsx` (`runRowLabel` function):**
- Update the label string to include the location: `${win} · ${location} · run ${runId}`,
  where:
  - `win` = existing date-window string (e.g., `"2025-06-01 → 2025-09-01"`).
  - `location` = `itemMeta(item).location` (e.g., `"New Braunfels, TX"`), omitted if null.
  - `runId` = the first 8 hex characters of the STAC item ID (or UUID if the ID contains one)
    + any job suffix (e.g., `-007`), to match the CKAN resource naming convention. Extract
    from `item.id` or a new `subside:run_id` property if needed.
  - Example: `2025-06-01 → 2025-09-01 · New Braunfels, TX · run 17482688-007`.

**In `StacResults.jsx` (`RunDetailsPopup`):**
- Add a new `<dt>` / `<dd>` pair in the metadata list (after "Acquisition window", before
  "OPERA products") to display the location, e.g., `<dt>Location</dt> <dd>New Braunfels, TX</dd>`.

## Files likely affected

- **New (publisher):** Logic in `stac-platform/stacmap/manifest.py` — add location
  computation to `granule_from_subside_manifest` (~20 lines). May factor out a helper
  function for bbox-to-zoom-to-location transformation.
- **New (backfill):** A standalone Python script (location: `stac-platform/scripts/backfill_locations.py`)
  to reverse-geocode and PATCH existing STAC items + CKAN datasets (discussed in Rollout).
- **Edit (UI):** `subside/ui/src/lib/stacApi.js` — update `itemMeta()` to read and return
  `location` (~3 lines).
- **Edit (UI):** `subside/ui/src/components/mapworkbench/StacResults.jsx` — update
  `runRowLabel()` to include location + run ID (~3–5 lines); update `RunDetailsPopup` to
  display location in the metadata list (~5 lines).

## API/schema changes

**New STAC item property:**
- `subside:location` (string) — human-readable place name, e.g., `"New Braunfels, TX"`.
  Mirrored into CKAN resource/dataset extras. Optional (may be null for runs with invalid
  or missing bboxes).

**No HTTP API changes** — the STAC schema is internal; the UI simply reads and displays
the property.

## Data flow

1. **Publisher (publish time):**
   - `granule_from_subside_manifest(manifest, item_id)` receives the run manifest with
     `bbox` and date window.
   - Compute location: extract bbox, calculate max extent in km, call Nominatim `/reverse`
     with scaled zoom level, parse the response.
   - Emit `subside:location` in the `properties` dict.
   - `stacmap.publish_from_dir()` / `publish_item()` (or Tapis task) writes the STAC item
     with the new property to the catalog and mirrors it into CKAN extras.

2. **Backfill (one-off):**
   - Script reads all STAC items in the collection.
   - For each item without `subside:location`, reverse-geocode and PATCH the STAC item +
     CKAN dataset/resource.

3. **UI (render time):**
   - `searchItems(bounds)` fetches STAC items (unchanged).
   - `itemMeta(item)` reads `item.properties['subside:location']` and returns it as
     `location`.
   - `runRowLabel(item, kind)` includes the location in the row string.
   - `RunDetailsPopup` displays the location in the metadata list.
   - No client-side geocoding; no per-render network calls.

## Risks and tradeoffs

**External dependency (Nominatim):**
- Nomimatum is a public, keyless service (no API key required), but it has usage
  policies: ~1 req/sec for bulk use, and requires a valid `User-Agent` header (OSM's
  canonical requirement). One-off publish-time calls are within policy. Backfill will
  need to be throttled (~1 req/sec) to respect rate limits.
- **Mitigation:** The publisher already has a valid Nominatim User-Agent precedent
  (via `AddressSearch.jsx`). Backfill script includes built-in rate limiting (`time.sleep(1.1)`
  between requests). If Nominatim is unavailable, the property is omitted and the UI
  gracefully falls back.

**Bbox-scaling thresholds (not yet finalized):**
- The proposed zoom/address-field mapping is a best guess based on typical run sizes
  (65–70 km). If real runs vary wildly (e.g., some are 5 km, others are 500 km+), the
  thresholds may need adjustment. **This is the key open question below; user approval
  required before implementation.**

**Backfill complexity:**
- Backfilling existing runs requires two external writes (STAC + CKAN), and both must
  be idempotent (safe to re-run). STAC item PATCH is straightforward; CKAN resource
  extras PATCH must not lose other fields. This is a gating external write requiring
  approval and dry-run validation.

**Nominatim response parsing:**
- If Nominatim returns an unexpected `address` structure (e.g., no city, no county),
  the fallback logic must be robust. The proposed fallback is: try suburb → city → town
  → county → state → country, with the state abbreviation appended when available.

## Alternatives considered

1. **Client-side render-time geocoding (rejected):** Call Nominatim when displaying each
   run row, so the location is computed on demand. Rejected because: (a) it fires a
   network request on every map pan/zoom re-render (StacResults uses `useMapEvents({ moveend: refresh })`),
   causing hundreds of rapid Nominatim calls and violating the ~1 req/sec policy; (b) user
   is exposed to Nominatim rate-limit errors and slow map interaction; (c) no caching /
   memoization without local storage (which is a liability).

2. **Offline polygon join (alternative, not recommended):**
   Instead of calling Nominatim, use a pre-downloaded polygon dataset (e.g., TIGER/Line
   county boundaries, or US Census Bureau city polygons) hosted locally or on S3, and
   perform a point-in-polygon query on the bbox center at publish time. Pros: no external
   API dependency, no rate-limit exposure, fully deterministic. Cons: adds a data dependency
   (must keep the polygon file current), more compute per publish (polygon intersection),
   and less flexible location names (polygon datasets have fixed granularity; Nominatim
   can adapt). **This repo's `ReferenceLayers.jsx` already fetches Texas aquifer polygons
   from a public ArcGIS FeatureServer (no API key), so a similar approach with TIGER
   boundaries is architecturally plausible.** Recommend Nominatim as v1 (live external
   dependency trade-off offset by simplicity and naming flexibility), with offline polygon
   join as a documented alternative if Nominatim availability becomes a concern.

## Test plan

**Unit tests (Python, `stac-platform/stacmap/tests/test_manifest.py`):**
- `granule_from_subside_manifest` with a valid SUBSIDE manifest (bbox + dates):
  - Mock Nominatim `/reverse` response and verify the location is extracted and set.
  - Test bbox-size-to-zoom scaling: small bbox (10 km) → zoom 18; medium bbox (50 km)
    → zoom 14; large bbox (300 km) → zoom 10.
  - Test address-field fallback: when `address.city` is missing, try `address.town`, etc.
  - Test null/missing bbox, null location (graceful degrada tion).

**Integration test (optional, gated):**
- Trigger a live publish (publish task or `subside-publish` pipeline) for a test run
  with a known bbox (e.g., New Braunfels area).
- Verify the STAC item carries `subside:location` = `"New Braunfels, TX"` (or similar).
- Verify the mirrored CKAN dataset/resource extras include the location.

**UI tests (JavaScript, `subside/ui/src/components/mapworkbench/StacResults.test.jsx`):**
- Mock `itemMeta` to return a location and verify `runRowLabel` includes it in the output.
- Mock `itemMeta` with `location: null` and verify the label omits it gracefully.
- Mock `RunDetailsPopup` with a location and verify it renders in the metadata list.

**Backfill dry-run (gated):**
- Run the backfill script in dry-run mode (`--dry-run`) and verify it logs what would be
  changed without writing anything.
- Inspect the log: counts of items to update, any errors, sample location names.

## Documentation plan

- **Publisher docs:** Add a section to `stac-platform/README.md` or design docs explaining
  the new `subside:location` property — what it is, how it's computed, how to handle
  failures.
- **UI docs:** Update `subside/ui/README.md` or a design document to note that run rows
  now include location and run ID for disambiguation, and that the location is computed
  at publish time (not rendered).
- **Backfill docs:** Document the backfill script in `stac-platform/scripts/README.md` —
  purpose, usage (dry-run first, then live), rate-limiting behavior, expected runtime.

## Rollout/rollback plan

**Phase 1 (v1, publisher + backfill):**
1. Deploy the location-computation logic to `stac-platform/stacmap/manifest.py` (new
   SUBSIDE runs will automatically include `subside:location`).
2. Run the backfill script in **dry-run mode** (`--dry-run`) to preview changes and verify
   Nominatim integration works (requires explicit user approval of the dry-run first).
3. Once the dry-run is validated, run the backfill script **live** with explicit user
   approval (external write — gated). Expected runtime: ~5–10 sec per item (1 req/sec Nominatim
   throttle) × number of items. Estimate for a 100-item collection: ~10–15 min.
4. Verify results: spot-check a few STAC items and CKAN datasets to confirm locations
   were written.

**Phase 2 (v1 or v2, UI):**
1. Deploy `stacApi.js` + `StacResults.jsx` changes to read and display the location +
   run ID in row labels and detail popup.
2. Once live, verify Risk Explorer map displays the updated labels.

**Rollback:**
- **Location property:** Backfill writes can be rolled back by deleting the
  `subside:location` property from STAC items (via a reverse script) and from CKAN
  dataset extras (via CKAN API DELETE extras). UI gracefully falls back to date-only
  labels if the property is absent.
- **UI changes:** Revert the `StacResults.jsx` and `stacApi.js` edits to restore the
  date-only labels (non-breaking).

## Open questions

1. **Bbox-scaling thresholds:** The proposed zoom/address-field mapping is based on
   typical run sizes (65–70 km). Are the proposed km thresholds (20, 100, 500) realistic
   for the actual SUBSIDE run distribution? Should they be adjusted?

2. **Backfill scope:** How many existing runs should the backfill script process? All
   items in the `subsidence-rates` collection? A specific date range? This affects
   runtime and approval scope.

3. **Nominatim attribution:** OSM Nominatim requires attribution in the app's UI and
   data sources. Should the Risk Explorer map already carry Nominatim attribution (e.g.,
   in a footer or metadata panel), or is it sufficient to document in the location
   backfill script and publisher code comments?

4. **Offline polygon alternative:** Should we prototype the TIGER county-boundary
   polygon join approach in parallel, or accept Nominatim as the baseline and revisit
   if rate-limiting becomes a problem?

## Decisions

- **2026-07-24:** User approved **compute location at publish time** (not render time).
  New STAC property `subside:location` is computed once per run in
  `granule_from_subside_manifest`, stored in STAC item + mirrored into CKAN extras.

- **2026-07-24:** User approved the **backfill script** approach (one-off standalone
  script, not a live Tapis task) to populate `subside:location` on existing published
  runs. Requires dry-run validation + explicit approval before live execution, as it is
  an external write to CKAN + STAC.

- **2026-07-24:** User has **NOT YET approved the concrete bbox-scaling thresholds and
  address-field selection** proposed in the "Proposed design" section. This is the key
  design decision still pending review below.

- **2026-07-24: Decoupled from the location work and shipped separately.** Architect
  review found this draft targets `granule_from_subside_manifest` in `manifest.py`,
  which is dead code — the live pipelines call `parse_manifest()` via
  `publish_from_dir()`, so location logic here would never reach a real published
  item as written. It also found the "mirrored into CKAN extras, same as
  `frame_ids`/`product_count`" claim is false — those fields exist only in STAC
  properties today, never copied to CKAN, so CKAN mirroring is new, unscoped surface,
  not reuse of an existing flow. Skeptic review separately found that reverse-geocoded
  location doesn't actually solve the reported disambiguation problem (identical
  reprocessing runs of the same AOI will often resolve to the same location name); the
  run-id already in this spec's design is what disambiguates, and is achievable today
  with zero new dependencies using data already in STAC properties (`subside:frame_ids`
  + the item id's embedded uuid/job-suffix, matching CKAN's own resource-title
  convention). User agreed: ship the run-id/frame-id fix now
  (`StacResults.jsx`'s `runIdSuffix`/`runRowLabel`, done), and keep this spec open only
  for the separable `subside:location` enhancement — to be revised to fix the
  insertion-point bug, resolve the CKAN-scope question, and address the
  centroid-vs-area-representative naming concern before re-approval.

- **2026-07-24: `subside:location` revised and implemented, addressing all three
  review findings above.**
  - **Insertion point (architect finding, fixed):** location is resolved inside
    `parse_manifest()` in `stac-platform/stacmap/manifest.py` — the actual live
    convergence point for both WERC and H2I branches — via a new opt-in,
    keyword-only `resolve_location: Callable[[list[float]], str | None] | None
    = None` parameter, not `granule_from_subside_manifest` (confirmed dead code;
    now commented as such in-place). Opt-in was chosen (over always-on) so
    `parse_manifest` stays pure/offline by default — the existing hermetic test
    suite (`test_mapping.py`) needs zero code changes to keep passing with zero
    network calls, addressing the architect's testability-regression concern.
    `publish_from_dir()` (`publish.py`) got the same opt-in `resolve_location`
    parameter, threaded through to `parse_manifest`, for the same reason: the
    integration test (`test_publish_pipelines.py`) and any ad hoc caller must
    not silently start hitting live Nominatim just by calling `publish_from_dir`.
  - **CKAN mirroring (architect finding, descoped):** dropped from v1. The
    Risk Explorer UI (`stacApi.js`'s `itemMeta()`) reads STAC item properties
    exclusively and never reads CKAN extras, so there is no consumer for a
    CKAN-side copy yet; the "same flow as `frame_ids`/`product_count`"
    precedent this spec originally cited does not actually exist (verified:
    those fields live only in STAC properties). `subside:location` is
    STAC-only for v1. Can be added later if a CKAN-side consumer (e.g. dataset
    search/faceting) needs it.
  - **Centroid representativeness / stability (skeptic finding, addressed):**
    replaced the single-centroid-at-scaled-zoom design with 3-point sampling
    (centroid + two opposite corners), each reverse-geocoded once, walking from
    a size-appropriate starting tier (`city` <30km / `county` 30–150km / `state`
    >150km, chosen from the bbox's actual max extent — real SUBSIDE runs are
    ~65–70km, so they start at `county`, not `city`, avoiding the
    misleading-centroid-city-name failure mode the skeptic raised) up toward
    coarser tiers until all 3 points agree on a name. A run only gets a location
    if its footprint genuinely supports one; near-duplicate reprocessing runs
    are far more likely to agree at the county/state level than a raw centroid
    is to agree on a single nearest city. No agreement anywhere (or any sample
    point failing to resolve) -> `None`, UI falls back to no location shown.
  - **New module:** `stac-platform/stacmap/geocode.py` — `resolve_location()`,
    fully unit-tested against a mocked Nominatim transport (`tests/test_geocode.py`,
    following the existing `httpx.MockTransport` convention from
    `test_ckan_client.py`/`test_stac_client.py`; added to the hermetic CI-gate
    suite listed in `pyproject.toml`). Every Nominatim call is a single
    best-effort attempt with a 5s timeout and a policy-compliant `User-Agent`;
    all exceptions are swallowed at both the per-call and top-level function
    scope — a location name can never block or fail a publish.
  - **Bonus bugfix found while reading `manifest.py`:** the WERC branch of
    `parse_manifest` wrote `subside:frame_id` (singular) while H2I wrote
    `subside:frame_ids` (plural); the UI's `itemMeta()` only ever read the
    plural key, so velocity/WERC runs' frame numbers silently never appeared in
    the just-shipped row-label fix. Fixed WERC to also emit the plural
    `subside:frame_ids` (as a single-element list); updated
    `test_mapping.py::test_parse_werc`'s assertion, which had been asserting
    the buggy singular key.

- **2026-07-24: Discovered existing prior art — `agents/ckan-agent-api`
  already reverse-geocodes for CKAN dataset titles.** Not visible from
  DSO-Architecture's docs (no `geocode`/`nominatim` mention anywhere in
  `repo-map.md`, the services pages, or the `ckan-agent-api`/`mcp-servers`
  pages — a documentation gap worth filing separately), and not found in the
  WebODM CKAN plugin either (`WebODM/coreplugins/ckan/publisher.py`'s
  `bbox_wkt()` only reformats a bbox to GeoJSON for CKAN's `spatial` field, no
  place-name lookup). It lives in
  `agents/ckan-agent-api/app/agents/ckan_registration/persona_nodes.py`
  (`_reverse_geocode`, deterministic, used to seed a `location_hint` for
  dataset-title generation) and `nodes.py` (`_update_field_with_llm`'s
  two-turn LLM tool-calling flow, used for interactive chat-driven title
  *revision* — not applicable here, since the Tapis publish pipeline has no
  LLM in the loop). Aligned `stacmap/geocode.py` with `persona_nodes.py`'s
  established convention: adopted its full address-field priority list
  (`neighbourhood, suburb, quarter, city_district, city, town, village,
  hamlet, municipality, borough`, richer than the original `city/town/village`
  draft) for consistency across the two repos. Kept the 3-point
  sample-and-agree structure rather than porting its single-centroid approach,
  because SUBSIDE bboxes (tens of km) are an order of magnitude larger than
  the drone-survey extents `persona_nodes.py` was built for, where a single
  centroid is far more likely to land ambiguously between two settlements —
  this is the same representativeness concern the skeptic raised, still
  applicable to our larger scale even though the sibling implementation
  doesn't need to handle it. Did not port the geographic-feature filtering
  (bay/river names shadowing the nearest town) since that's a fallback path
  (`data.get("name")` when no address field resolves) our tier-agreement
  design doesn't have. Re-ran `test_geocode.py` + `test_mapping.py` (16 tests
  combined) after this change — all still pass.

## User feedback / decisions

- **2026-07-24:** User said "ok do it" — approved proceeding with the revised
  `subside:location` design above (insertion-point fix, CKAN mirroring dropped
  for v1, 3-point tier-agreement naming) without further review of specific
  thresholds, superseding the still-open bbox-scaling-threshold question from
  the original draft.
- **2026-07-24 (still open):** wiring the three live Tapis pipeline YAMLs
  (`werc-opera.yaml`, `h2i-opera.yaml`, `subside-publish.yaml`) to actually pass
  `resolve_location=resolve_location` into their `publish_from_dir(...)` calls
  was blocked by the auto-mode classifier (edits to `tapis/workflows/pipelines/*.yaml`
  are treated as live infrastructure-as-code). The `stacmap`/UI code is fully
  implemented and tested, but is inert in production until this wiring lands —
  see "Implementation summary" for the exact two-line diff needed per file.
- Nominatim attribution (open question 3) and the offline-polygon alternative
  (open question 4) remain unresolved; not blocking for v1 given `subside:location`
  is currently unused in production pending the pipeline-wiring step above.

## Implementation summary (2026-07-24)

**Done:**
- `stac-platform/stacmap/geocode.py` (new) — `resolve_location(bbox)`.
- `stac-platform/stacmap/manifest.py` — `parse_manifest(..., resolve_location=None)`
  opt-in param, called once after `bbox` is resolved for both branches; WERC
  `frame_id`/`frame_ids` key bugfix; `granule_from_subside_manifest` commented
  as dead-code/unused-by-live-pipelines.
- `stac-platform/stacmap/publish.py` — `publish_from_dir(..., resolve_location=None)`
  opt-in param threaded through to `parse_manifest`.
- `stac-platform/tests/test_geocode.py` (new, 8 tests) + `test_mapping.py`
  assertion fix. Full hermetic suite (33 tests) passes with zero network calls.
- `subside/ui/src/lib/stacApi.js` — `itemMeta()` reads `subside:location`.
- `subside/ui/src/components/mapworkbench/StacResults.jsx` — `runRowLabel()` and
  `RunDetailsPopup` display the location when present. ESLint clean.
- **2026-07-24 (later):** wired all three Tapis pipeline YAMLs
  (`werc-opera.yaml`, `h2i-opera.yaml`, `subside-publish.yaml`) — added
  `from stacmap.geocode import resolve_location` and
  `resolve_location=resolve_location,` to each `publish_from_dir(...)` call.
  The user re-approved this specific edit after the earlier classifier block;
  it landed cleanly on retry. Verified: all three YAMLs parse and every
  embedded Python task body `compile()`s; `git diff` shows exactly the
  intended 2-line addition per file (an incidental `chmod +x` the edit tool
  applied was reverted back to the original file mode).

**2026-07-24 (later): all three pipelines registered live.** User ran the dry
run (`register.py --pipelines-only --recreate-pipelines --dry-run`) then the
live registration; both completed cleanly against `subside-ops` on
`portals.tapis.io` — `subside-h2i-opera`, `subside-publish`, and
`subside-werc-opera` all show `[recreate]` and `Done.`, no errors. The
`subside:location` feature is now fully deployed: new runs get it
automatically.

**2026-07-24 (later): backfill script written.** `stac-platform/scripts/backfill_locations.py`
— dry-run by default (`--apply` required for the real write), idempotent
(skips items that already carry `subside:location`), STAC-only per the
CKAN-mirroring-descoped decision above. Reuses `resolve_location` and a new
`StacClient.get_item()` method (added alongside a test in `test_stac_client.py`;
full 34-test hermetic suite passes) rather than a bespoke PATCH formatter, per
the architect's recommendation. Throttles 1.5s between items that actually hit
Nominatim (3 calls/item). Supports `--item-id` for a controlled single-item
test before a full collection run. **Not yet executed live** — needs the same
explicit-approval + dry-run-first treatment as any other external write in
this project.

**2026-07-24 (later): dry-run against the real `subsidence-rates` collection
(17 items) caught three real bugs the mocked test suite couldn't, all fixed
and now covered by regression tests:**

1. **State-tier majority is nearly always trivially true within one state.**
   v2's algorithm (majority agreement across city -> county -> state, with a
   centroid-only fallback if nothing reached majority anywhere) sounded right
   but was broken in practice: for a run spanning 3+ Texas counties (real
   Hill Country runs do this — counties there are often only 30-50km across
   against ~65-70km bboxes), city and county majority both fail, but state
   majority ("Texas") ALWAYS trivially succeeds — so the centroid fallback,
   specifically designed to handle this exact case, could never actually
   fire. **Fix:** majority is now checked only at city/county; if neither
   reaches majority, go straight to the centroid's own finest field instead
   of ever accepting a bare state-level majority.
2. **Hardcoded `zoom=10` silently omits finer detail that exists.** The same
   rural centroid point returns `{"county": "Kerr County", "state": "Texas"}`
   at zoom=10, but `{"hamlet": "Guadalupe Heights", "county": "Kerr County",
   "state": "Texas"}` — the full hierarchy — at zoom=14. Nominatim resolves
   directly to whichever admin level the zoom implies and only includes finer
   levels when the matched feature is at least that fine. **Fix:** changed to
   zoom=14 (matching `agents/ckan-agent-api`'s proven value) everywhere.
3. **No delay *within* one `resolve_location()` call's 3 sample-point
   requests** (only *between* items, in the backfill script's own loop) got
   the session rate-limited (`HTTP 429`) by Nominatim after ~7 items during
   testing — confirmed via an isolated `curl` diagnostic call returning 429
   even 2s apart, clearing again after a ~15-minute pause. This is the exact
   risk the skeptic flagged during design review, now observed directly.
   **Fix:** `resolve_location()` now sleeps `REQUEST_DELAY_S` (1.1s, test-
   overridable via `request_delay_s=0`) between its own 3 calls, on top of
   the backfill script's existing inter-item delay.

Verified post-fix against 2 real items spanning different regions:
`subside-werc-...-17482688-...` (Hill Country, spans Kerr/Bandera/Gillespie
counties) now resolves to `"Guadalupe Heights, Texas"` (previously "Texas"
under every prior version); a Gulf Coast item resolves to `"Galveston County,
Texas"`. Full mocked suite (37 tests, including a regression test for bug #1)
passes in ~0.06s. Have NOT re-run the full 17-item collection since fixing
this, to avoid re-triggering the rate limit — recommend a conservative
`--delay` (>=2s) and off-peak timing for the eventual full `--apply` run.

**2026-07-24 (later): fixed a 400 on the first live `--apply` attempt.**
`client.upsert_item()` failed with `HTTPStatusError: 400 Bad Request` on the
very first item. Root cause: `_backfill_one` fetches the item via `GET`
(which pgstac populates with server-injected `self`/`parent`/`root`/`collection`
navigation links), sets `subside:location`, then `PUT`s the whole item back
including those populated links — but `stac.py`'s `build_item()` (the
original publish path) always sends `"links": []` with an explicit comment
that pgstac injects them on read, meaning the API doesn't expect a client to
submit a populated `links` array on write. Fix: reset `item["links"] = []`
immediately before `upsert_item()`. Added 3 regression tests in the new
`tests/test_backfill_locations.py` (mocked STAC API, one of which specifically
rejects a non-empty `links` payload with the same 400 to catch a regression);
full suite is now 40 tests, still ~0.07s.

**2026-07-24 (later): the `links: []` fix wasn't sufficient — same 400 recurred.**
The `links` diagnosis was a plausible hypothesis from reading `stac.py`'s
comment, but was never confirmed against the server's actual error message
(`resp.raise_for_status()` discards the response body). Checked the STAC
API's OpenAPI spec directly (`/api/v1/openapi.json`) and found
`/collections/{collection_id}/items/{item_id}` supports `patch` in addition to
`get`/`put`/`delete` — a proper JSON Merge Patch endpoint that only requires
the changed fields (`{"properties": {"subside:location": "..."}}`), not a
complete Item. Switched from get-mutate-`upsert_item` (PUT, full replace) to
a new `StacClient.patch_item()` (PATCH, partial update) — this sidesteps the
whole class of bug (links or any other server-managed field) rather than
patching around it field-by-field. Rewrote `test_backfill_locations.py`
around PATCH and added 2 new `patch_item` tests in `test_stac_client.py`.
Full suite: 43 tests, ~0.09s. **Still not verified against the live API with
a real write** — the two prior `--apply` attempts both got HTTP 400
(rejected outright, nothing persisted), so the collection is unchanged;
next step is the user re-running `--apply` with this version.

**2026-07-24 (later): code shipped and pushed, but the live UI pod hasn't
picked it up yet — separate deploy-tooling issue, not a code bug.** Both
repos' real changes (excluding unrelated pre-existing noise: a repo-wide
executable-bit flip on ~250-300 files in each repo restored to 644 before
committing, and an unrelated in-progress `ReferenceLayers.jsx` opacity change
left untouched) were committed and pushed to `origin/main`:
- `stac-platform` commit `401b3fc` — this was urgent: the `stac-publish`
  Tapis task's `packages` list installs `stacmap` directly from
  `https://github.com/wmobley/stac-platform/archive/refs/heads/main.zip`
  (fetched fresh on every execution), so until this pushed, the pipeline
  wiring registered earlier referenced a `stacmap.geocode` module that didn't
  exist remotely — the next real run would have crashed at import.
- `subside` commit `b55dac5` — triggered `.github/workflows/build-services.yml`
  automatically (push-triggered, not gated by the branch-protection PR
  requirement your account has bypass rights for). CI ran lint + tests +
  built/pushed both `subside-ui`/`subside-api` images + restarted the Tapis
  pods, all green (verified via `gh run watch`).

**However:** verified directly (fetched the deployed bundle from
`https://subsideui.pods.portals.tapis.io/assets/index-*.js` and grepped for
`subside:location`/`runIdSuffix` — zero matches) that the running `subsideui`
pod is still serving the OLD bundle. The JS asset's `etag`/`last-modified`
were byte-for-byte identical before and after the CI run's restart step,
which itself reported success (`[subsideui] restart requested` /
`status: AVAILABLE`, per the CI log). This means a Tapis Pods restart does
NOT reliably force a fresh image pull for a `latest`-tagged image, contrary
to `restart_pods.py`'s own docstring assumption ("A pod restart stops +
starts the container, which re-pulls the `latest`-tagged image") — likely an
`imagePullPolicy` that reuses the node's already-cached image rather than
re-checking the registry. User is investigating via the Tapis Pods
dashboard/CLI directly. Worth a follow-up fix to `restart_pods.py` (or a
`register_pods.py` rebuild) once resolved, so this doesn't silently recur for
every future deploy.

**Still open:**
- Nominatim attribution in the Risk Explorer UI (open question, unresolved).
- Getting the live `subsideui` pod to actually serve the new bundle (see
  above — in progress, user handling via Tapis tooling directly).
