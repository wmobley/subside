# SUBSIDE UI Accessibility Remediation

**Date:** 2026-09-29
**Status:** Source remediation deployed; fresh Monsido crawl pending
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

## Monsido follow-up

The live deployed DOM was verified after workflow `36629034563` completed successfully. The
Monsido page currently still displays the prior snippets and counts, including the old
`<span>|</span>` markup and the old `aria-label` values, while its new crawl is not showing a
completed result. The button-name finding is fixed in the deployed accessibility tree, but formal
automated closure of the contrast and ARIA categories remains pending a fresh completed crawl.

The next audit should capture the URL, selector, computed accessible name, and owning package for
each remaining result. Leaflet/Geoman-generated controls should be classified separately from
application markup before changing vendor behavior.

## Remaining manual review

The audit still requires keyboard and visual verification for keyboard operation, focus order and
visibility, modal behavior, color-independent status meaning, zoom/reflow, hover/focus content,
page titles, heading quality, instructions, and error-message quality. The source changes above
address the identifiable application-owned cases, but they do not replace an end-to-end keyboard
pass or a rerun of the deployed accessibility checker.

## Acceptance next step

Rerun the same accessibility check against the deployed version and retain a before/after export
with selectors or screenshots. Once that crawl completes, classify each remaining automatic result
as fixed, third-party-generated, not reproducible, or deferred.
