# SUBSIDE UI Accessibility Remediation

**Date:** 2026-09-29
**Status:** Source remediation deployed; keyboard/manual review completed; fresh Monsido crawl pending
**Scope:** `subside/ui`

## Source audit reviewed

The source audit was exported as `export_domain_205365_accessibility_checks_20260929_1453.csv`.
It contains 95 WCAG checks:

- 40 automatic error checks
- 22 warning checks
- 33 manual review checks

The CSV does not include page URLs, selectors, DOM snapshots, or screenshots. Therefore, a
non-zero page count identifies a reported category but does not identify the exact element or
prove that the element belongs to application code rather than Leaflet/Geoman-generated markup.

The automatic error categories associated with pages were:

- WCAG 1.4.3 text contrast — high severity, 6 pages
- WCAG 4.1.2 link missing an accessible name — high severity, 1 page
- WCAG 4.1.2 button missing an accessible name — high severity, 1 page
- WCAG 4.1.2 incorrect ARIA state or property — medium severity, 6 pages

## Fixes implemented

### Contrast and focus visibility

- Replaced the portal's `--tacc-text-light` value with `#5f6368`.
- The new token provides approximately 6.05:1 contrast on white and 5.50:1 on `#f4f4f4`,
  compared with approximately 2.19:1 for the previous `#afafaf` value.
- Added a consistent `:focus-visible` treatment for links, buttons, form controls, and
  disclosure controls.
- Removed rules that suppressed the focus outline on the main search and map address inputs.

Files: `ui/src/styles.css`

### Form labels and grouping

- Added a `fieldset` and `legend` for the custom dataset bounding-box filter.
- Added explicit labels and stable IDs for minimum/maximum latitude and longitude inputs.
- Added explicit labels and stable IDs for the analysis pipeline and start/end date controls.
- Continued to use native labels rather than placeholders as the accessible name.

Files: `ui/src/components/datasets/DatasetFilters.jsx`,
`ui/src/components/mapworkbench/SubsideAnalysis.jsx`, `ui/src/styles.css`

### Interactive structure and names

- Removed action buttons from inside checkbox labels in the layer and previous-run panels.
- Preserved the checkbox label relationship while making the action button a sibling control.
- Made per-run action names contextual, for example, “Kerr County run actions,” rather than
  giving every action button the same generic name.

Files: `ui/src/components/mapworkbench/SubsideLayers.jsx`,
`ui/src/components/mapworkbench/StacResults.jsx`, `ui/src/styles.css`

### Automated-check findings from the deployed audit

- Replaced the visible partner-institution `|` characters with a decorative CSS divider so
  separator text is no longer evaluated as page content or low-contrast text.
- Changed the partner-institution wrapper to a labeled `nav` and removed the invalid
  `aria-label` from the plain account wrapper `div`.
- Added accessible names and titles to the Geoman rectangle, polygon, edit, and delete map
  controls. These were the four unnamed buttons reported on Risk Explorer.
- Updated the Data format chips and Risk Explorer map instructions to use the AA-readable
  `--tacc-text-light` token on the light-gray surface. Monsido identified these as the remaining
  contrast sources: 161 format-chip instances on Data and one map instruction paragraph on Risk
  Explorer.

Files: `ui/src/components/PortalChrome.jsx`, `ui/src/components/mapworkbench/SubsideAnalysis.jsx`,
`ui/src/styles.css`

### Upload, errors, and asynchronous status

- Replaced the `hidden` GeoJSON input with a visually-hidden but keyboard-reachable native file
  input and an associated visible label.
- Added a visible focus treatment when the file input owns focus.
- Marked actionable analysis, results, and history errors as `role="alert"`.
- Marked run progress and fallback run status as polite live status regions without forcing the
  entire multi-step panel to be re-announced on every poll.

Files: `ui/src/components/mapworkbench/SubsideAnalysis.jsx`,
`ui/src/components/mapworkbench/RunProgress.jsx`, `ui/src/styles.css`

### Workflow documentation dialog

- Added an explicit dialog heading relationship with `aria-labelledby`.
- Added initial focus, Escape-to-close, Tab containment, and focus restoration to the trigger.
- Gave the close control the name “Close dialog.”

File: `ui/src/components/mapworkbench/SubsideAnalysis.jsx`

### Keyboard, status, and responsive fixes

- Named the actual Geoman keyboard controls on their focusable parent buttons and labeled the
  interactive map as an `Interactive risk map` region.
- Added polite live status messaging for Forecast loading, running, and completed results, plus
  `role="alert"` for Forecast errors.
- Added `aria-busy` to the Forecast form while an estimate is running.
- Constrained the Data header, filter panel, dataset cards, and Forecast form grid items so they
  can shrink instead of forcing horizontal document overflow at narrow widths.

Files: `ui/src/components/mapworkbench/SubsideAnalysis.jsx`, `ui/src/components/ForecastTool.jsx`,
`ui/src/styles.css`

## Verification completed

- `npm run lint` — passed with no warnings or errors after separating shared modules from React
  component modules.
- `npm run build` — passed; Vite transformed 951 modules and produced the production bundle.
- `git diff --check` — passed with no whitespace errors.
- Static source review confirmed that the changed layer rows no longer nest buttons inside labels.
- The deployed Risk Explorer accessibility tree now exposes `Draw rectangle`, `Draw polygon`,
  `Edit area`, and `Delete area` as named buttons; the partner links are exposed in a named
  region.
- No dedicated component or automated accessibility test suite is configured in `ui/package.json`;
  browser keyboard checks and the deployed audit remain required.
- The local build required restoring the missing optional Rollup native package. No application
  dependency or lockfile change was retained.

## Keyboard and manual review completed

The deployed build from workflow `36639374322` (commit `0222c22`) was checked with keyboard
interaction and a browser accessibility tree:

- **Tab order and visible focus:** Representative Home, Forecast, Data, and Risk Explorer
  traversals reached the site navigation, page controls, map controls, layer actions, form
  controls, and footer links in a usable order. Sampled focus targets showed a visible white
  outline with a dark offset ring.
- **Map controls and layer actions:** Risk Explorer exposes a named `Interactive risk map`
  region. Zoom, Geoman draw/edit/delete controls, layer checkboxes, and contextual layer-action
  buttons have usable names. Opening a layer-action menu with Space and closing it with Escape
  returned focus to the invoking button.
- **Dialog Escape and focus restoration:** The workflow documentation dialog source implements
  initial focus, Tab containment, Escape-to-close, and restoration to its trigger. The workflow
  dialog itself could not be opened live because the deployed session was unauthenticated; the
  layer-action menu Escape/focus-restoration path was verified live.
- **Form controls and errors:** Forecast numeric inputs, selects, disclosure, and action buttons
  were exposed with names. A failed Forecast request was exposed as a `role="alert"` error. A
  successful result announcement was not live-verified because the API returned the transient
  Tapis `/pod-splash` startup error during the QA window.
- **Live status updates:** Forecast loading/running/result status and map run-progress status are
  implemented as polite live regions. The error announcement was verified live; successful
  Forecast completion remains a follow-up once the API is available.
- **Keyboard traps:** A 90-Tab Risk Explorer traversal did not repeat an active target, providing
  evidence of no keyboard trap in the sampled route.
- **Zoom/reflow:** At 640px and 320px viewport widths (equivalent to approximately 200% and 400%
  desktop zoom for this review), Forecast, Risk Explorer, and Data all measured document and body
  widths equal to the viewport with no off-screen visible controls. The Data and Forecast layout
  constraints were fixed in commits `c7e0561`, `0d83b70`, and `0222c22`.

## Monsido follow-up

The live deployed DOM was verified after workflow `36629034563` completed successfully. The
Monsido page currently still displays the prior snippets and counts, including the old
`<span>|</span>` markup and the old `aria-label` values, while its new crawl is not showing a
completed result. The button-name finding is fixed in the deployed accessibility tree, but formal
automated closure of the contrast and ARIA categories remains pending a fresh completed crawl.

The next audit should capture the URL, selector, computed accessible name, and owning package for
each remaining result. Leaflet/Geoman-generated controls should be classified separately from
application markup before changing vendor behavior.

## Remaining review items

- Re-run the Forecast success-path status check after the Tapis API pod is fully available.
- Open the authenticated workflow documentation dialog once a TACC session is available and
  record the live Escape and focus-restoration result.
- Rerun Monsido and retain the before/after export; the current Monsido view still represents the
  prior crawl.

## Acceptance next step

Rerun the same accessibility check against the deployed version and retain a before/after export
with selectors or screenshots. Once that crawl completes, classify each remaining automatic result
as fixed, third-party-generated, not reproducible, or deferred.
