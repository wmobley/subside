# SUBSIDE mobile responsive review

**Date:** 2026-10-26
**Scope:** Existing React UI; one responsive site for all devices.
**Status:** Implemented locally; browser checks passed; not deployed.

## Behavior

- All five primary navigation links remain visible on phones and wrap as needed;
  the current page is identified with `aria-current`.
- Home and About cards fit their containers. Mobile footer links use two columns.
- Data filters, custom bounding-box fields, Forecast fields and analysis dates
  fit narrow screens. Visible mobile form controls use at least 16px text.
- Mobile buttons, map toolbar controls and layer action buttons have at least
  44px height; icon action buttons also have 44px width.
- Layers controls live outside the map. At widths up to 1100px, a labeled
  hamburger-style **Layers and legends** button opens a full-screen native
  dialog. Its heading and Close button stay visible while its contents scroll.
  Native modal behavior keeps focus inside the dialog; Close or Escape returns
  focus to the launcher, and background page scrolling is locked only while
  the modal is open. Closing preserves layer selections and the previous-run
  list. On larger screens, the same panel is a separate 260px sidebar beside
  the map, without modal focus trapping or page scroll locking.
- Displacement and Subsidence Velocity legends and previous runs scroll in a
  labeled, keyboard-focusable region. Managing layers no longer covers the map.
  Search, zoom and drawing controls remain on the map.
- Layer action menus stay within the viewport and dismiss on an outside pointer
  press (including touch) or Escape. In the modal they render inside its top
  layer; Escape dismisses the action menu first. Zoom In closes the dialog to
  return to the map.

## Design references

The user approved an all-page responsive pass using these references:

- [BrandStory mobile usability guide](https://www.brandstory.ae/blogs/how-to-fix-mobile-usability-issues-step-by-step-technical-guide/):
  fluid widths, readable forms, separated touch targets and viewport checks.
- [SiteWare mobile dashboard UX](https://getsiteware.com/dashboard-ux-mobile-first-design-and-responsive-considerations/):
  adapt layouts and information hierarchy to available space.
- [Pinky Jain dashboard case study](https://medium.muz.li/i-turned-a-complex-dashboard-into-a-seamless-mobile-experience-heres-what-i-learned-0bb244db64cd):
  collapsible detail and spacing for touch interaction.
- [Roth et al., Making maps & visualizations for mobile devices](https://doi.org/10.1080/17489725.2023.2251423):
  the supplied full PDF was reviewed for Table 2 (journal pages 416–418) and
  the user interaction discussion (pages 450–453). Relevant guidelines include
  hiding supplementary legends initially, responding to aspect ratio, readable
  typography, preserving map space and visible interaction affordances.
  These are design guidance rather than evidence of usability outcomes for
  SUBSIDE; physical-device and user testing remain useful.

## Validation performed

- Production build and ESLint passed. Vite reports its large-chunk warning.
- Chromium browser checks covered Home, Risk Explorer, Forecast, Data and About
  at widths 320, 390, 768, 1024 and 1440px. Document width matched viewport width
  and all five navigation links remained visible.
- Forecast fields and a populated result/chart were checked with intercepted
  API responses; custom Data bounding-box inputs and the spatial map were
  checked at 320px. No forecast or analysis was submitted to a real backend.
- A simulated signed-in user with a long username was checked at 320px. Date
  fields and the hidden upload input no longer enlarge document width.
- Intercepted STAC responses populated previous-run lists with eight runs per
  kind. With both legends enabled, PageDown and wheel events advanced the
  bounded list and the final run was reachable. Map keyboard position remained
  unchanged. A separate touch-enabled Chromium session with ten runs per kind
  scrolled the legend by swipe while the map position remained unchanged.
- After the user's feedback that on-map Layers still obscured the map, the
  overlay was replaced with the full-screen mobile dialog and external desktop
  sidebar. Fresh browser contexts at 320, 390, 768, 1024, 1100, 1101 and 1440px
  confirmed no page overflow, external placement and full-viewport modal bounds
  through 1100px. A 390 → 1440 → 844×390 transition confirmed mode changes,
  focus handling and release of page scroll locking. Navigation away also
  released scroll locking. A ResizeObserver keeps Leaflet dimensions current.
- Touch-enabled Chromium taps opened and closed the dialog; both legends with
  ten runs per kind remained selected across reopen. PageDown scrolled the list
  without moving the map. Action menus rendered inside the modal; their Escape
  handling dismissed the menu while leaving the dialog open. Native dialog
  Escape restored focus to the launcher.
- Narrow-page and map screenshots were inspected. An independent read-only
  reviewer inspected the responsive and menu changes.

## Repeatable manual checks

1. Start the UI using the existing documented `npm run dev` command in `ui/`.
2. Visit every primary page at the widths above and at a short landscape size.
   Check navigation, text wrapping, visible focus and absence of horizontal
   page scrolling. Also check a signed-in analysis form with a long username.
3. Open Data's custom spatial filter and map. Check all coordinate inputs,
   drawing controls and filter reset. On Forecast, check both the input form
   and a populated result without relying on clipped chart labels.
4. With enough STAC runs available, open **Layers and legends**, enable both quantities and
   scroll to the final run by wheel, touch and keyboard. Focus the labeled
   region before using Arrow/Page keys. Confirm the map stays still.
5. Close the dialog and confirm the map is unobstructed. Reopen it and verify
   layer selections persist. Open a run's actions menu near the screen edge;
   check menu bounds, outside-tap dismissal and Escape. Confirm Zoom In returns
   to the map. Tab repeatedly to check modal focus stays inside, then use Escape
   and confirm focus returns to the launcher.
6. Rotate the device with Layers open. Verify full-screen bounds and scroll
   height. Resize past 1100px and back: the sidebar should be nonmodal on
   desktop, the mobile dialog should close, and page scrolling should recover.

## User feedback and correction

The initial collapsible on-map panel passed overflow checks but still obscured
the geography when expanded. The user requested a full-screen modal opened by
a hamburger-style mobile button. The final layout implements that interaction
and removes the on-map Layers control at every screen size. No duplicate mobile
site or duplicate layer state was introduced.

## Limits and follow-up

Browser checks used desktop Chromium and mobile emulation, not a physical iOS
or Android device. Verify mobile Safari browser chrome, native date controls,
screen-reader navigation and pinch zoom on devices before release. Large
JavaScript bundles remain a separate performance concern. No deployment,
API/schema changes or authentication behavior changes are part of this work.
