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

## Do-Not-Repeat

<!-- Mistakes made and corrected. Each entry prevents the same mistake recurring. -->
<!-- Format: [YYYY-MM-DD] Description of what went wrong and what to do instead. -->

## Decision Log

<!-- Significant technical decisions with rationale. Why X was chosen over Y. -->
