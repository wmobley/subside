# Editing the SUBSIDE website content

The text and lists shown on the site's **About** page live in this folder as
plain Markdown files. You can edit them without touching any code — the easiest
way is to edit a file directly on GitHub (open the file, click the pencil ✏️,
make your change, and "Commit changes"). The site rebuilds and your edit goes
live shortly after.

## What's here

```
content/
  about.md        ← the mission / goal paragraph at the top of the About page
  partners/       ← one file per Partner Organization card
  goals/          ← one file per "What we're building" card
```

## How a file is structured

Each file has two parts: a **frontmatter** block between `---` lines (short
labelled fields), and the **body** text below it (free prose, where you can use
**bold**, [links](https://example.com), and bullet lists).

A partner file (`partners/`) looks like this:

```markdown
---
name: Texas Water Development Board
abbr: TWDB
role: Project sponsor
url: https://www.twdb.texas.gov/
---
The state water-planning and data agency. TWDB defines the subsidence
data needs and provides guidance.
```

A goal file (`goals/`) looks like this:

```markdown
---
title: Centralize the data
---
Bring Texas's scattered subsidence datasets into one open catalog.
```

## Common edits

- **Change wording:** edit the body text or a frontmatter field. Keep the
  `key:` labels exactly as they are.
- **Reorder the cards:** rename the number at the front of the filename
  (`1-`, `2-`, …). Cards are shown in that order.
- **Add a card:** copy an existing file in the same folder, give it the next
  number, and edit it.
- **Remove a card:** delete its file.

## A few rules

- Keep the `---` lines and the `key:` labels — only change what comes after the
  colon, or the body text below.
- Don't rename the `about.md` file or the `partners/` and `goals/` folders.
- If something looks broken after an edit, check that both `---` lines are still
  there.
