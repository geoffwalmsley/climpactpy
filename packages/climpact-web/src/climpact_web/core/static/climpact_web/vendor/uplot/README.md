# uPlot (vendored)

`uPlot.iife.min.js` and `uPlot.min.css` are [uPlot](https://github.com/leeoniya/uPlot)
**1.6.32**, copied unchanged so the charts (#75) work offline (no CDN). They ship inside the
`climpact-web` wheel as static files and load only on pages with a chart
(`components/chart_scripts.html`).

| File | Source | SHA-256 | Size |
| --- | --- | --- | --- |
| `uPlot.iife.min.js` | <https://cdn.jsdelivr.net/npm/uplot@1.6.32/dist/uPlot.iife.min.js> | `19c8d4c6ad88929a79f4ae49d6f7161566dfd0ba3d15cc495e974f787eb78f1f` | 51,081 bytes (22.0 KB gzipped) |
| `uPlot.min.css` | <https://cdn.jsdelivr.net/npm/uplot@1.6.32/dist/uPlot.min.css> | `df630c6a8d6f8eeaff264b50f73ce5b114f646ffd9a0bb74f049b0a00135fa04` | 1,857 bytes (0.8 KB gzipped) |
| `LICENSE` | <https://cdn.jsdelivr.net/npm/uplot@1.6.32/LICENSE> | `8f989229699b4fe2f1a0432d0e9edc338a8a911e250e2d1b01ecd770a5f5b1bd` | 1,078 bytes |

The JavaScript is the same bytes at `https://unpkg.com/uplot@1.6.32/dist/uPlot.iife.min.js`.

- Licence: MIT (Copyright (c) 2022 Leon Sorokin), in `LICENSE` beside the files
- Released: 2025-03-14; downloaded: 2026-11-14

`tests/test_charts.py` checks each file against the SHA-256 above. To upgrade, download the
new version's three files from the same paths, then update the version, URLs, hashes and
sizes here. `js/charts.js` reads two undocumented fields of uPlot's axes (`_splits`,
`_values`) for the SVG export and falls back to its own ticks without them; check the SVG
export after an upgrade.
