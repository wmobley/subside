# SUBSIDE

React/Vite scaffold for the SUBSIDE Data Discovery Portal.

## Run

```bash
npm install
npm run dev
```

The dev server is configured for `http://127.0.0.1:5174/`.

If you want live FloPy dataset calls, also run the existing Flask API from
`../flopy-interactive`:

```bash
python -m flopy_interactive.api
```

The Vite proxy forwards `/api/*` to `http://127.0.0.1:5050`.

## Structure

- `webpage_Examples/example.html`: original static wireframe reference.
- `notebookExamples/`: notebook references and experiments.
- `src/App.jsx`: React state container and page composition.
- `src/config.js`: audience modes, stats, tabs, dataset summaries, and feature cards.
- `src/api.js`: shared JSON fetch helper for API calls.
- `src/modeling.js`: WEL/RCH defaults, map marker styling, and publish helpers.
- `src/components/`: reusable portal sections, map workbench, and workflow modal.
- `src/styles.css`: SUBSIDE/TACC visual system and responsive layout.
