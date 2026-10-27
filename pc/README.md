# PC app (`stashdisplay`)

Python 3.12+. Runs on Windows (target) and macOS (development).

## Setup

```bash
cd pc
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
```

On Windows, use `.venv\Scripts\pip` and `.venv\Scripts\python` instead.

## Preview the pages with demo data

```bash
.venv/bin/python -m stashdisplay preview --out preview --scale 2
```

This writes, for each page, `pageN-<id>.png` (exactly what the screen will show), `pageN-<id>-overlay.png` (the transparent layer sent to the screen), and `all-pages.png` with every page side by side.

## Tests

```bash
.venv/bin/python -m pytest
```

## Code map

| Module | Role |
|---|---|
| `history.py` | Totals over time, saved to `history.json` |
| `stats.py` | div/h, session gain, today, best hour, sparkline |
| `pages.py` | Page definitions (JSON), defaults, preset pages |
| `render/templates.py` | Page templates and their slots |
| `render/widgets.py` | Widget types, their options, how they draw |
| `render/renderer.py` | Header, overlay, background, dots, preview |
| `render/data.py` | Metrics and formatting for a render |
| `sources/` | Data sources: `demo.py` now, WealthyExile and poe.ninja later |
