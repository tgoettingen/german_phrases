# German Phrases: browser app

The phone app from `mobile/` with a layout for desktop browsers too: the tabs are a left
sidebar at 900 px and wider, and at the bottom on narrow windows and phones. Same tabs
(Study, Browse, Auto play, Lists, Progress, Settings), same spaced repetition and the same
`progress.json` format as `trainer.py` (export/import in Settings).

## Online

<https://htpe.github.io/german_phrases/>, published by `.github/workflows/pages.yml`
on every push to `main` that changes `web/`. Open it on any device. To install it as an app:

- **Android**: Chrome → ⋮ → Add to Home screen → Install
- **macOS**: Safari → File → Add to Dock
- **iPhone/iPad**: Safari → Share → Add to Home Screen

After the first visit it works offline. A new version is picked up the next time the app is
opened while online. Progress stays on each device; move it with Settings → Export / Import.

### One-time setup on GitHub

On <https://github.com/htpe/german_phrases>:

1. **Turn on Actions** (needed because the repo is a fork): open the **Actions** tab. If it says
   "Workflows aren't being run on this forked repository", click
   **I understand my workflows, go ahead and enable them**.
2. **Turn on Pages**: **Settings → Pages → Build and deployment → Source: GitHub Actions**.
3. **Deploy**: **Actions** → **Deploy web to GitHub Pages** (left list) → **Run workflow** (branch
   `main`) → **Run workflow**. After about a minute the run is green and shows the link.
4. **Open** <https://htpe.github.io/german_phrases/> and install it as described above.
5. **Move your progress** (optional): on the PC, export `progress.json` (Settings → Export) or take
   `data/progress.json`, then on the phone choose Settings → Import.

After that, every push that changes `web/` deploys by itself.

If something goes wrong:

- The run fails at *configure-pages*: step 2 isn't done yet. Do it, then run the workflow again.
- The page shows 404: wait 1–2 minutes after the green run, then reload.
- The phone shows an old version: close the app and open it again while online.

## Run locally

ES modules and `fetch` don't work from `file://`, so serve the folder over http:

```bash
cd web
python -m http.server 8000
```

Then open <http://localhost:8000>. Progress is stored in the browser (localStorage, key
`german-phrases/progress`). Use Settings → Export / Import to move it to or from the PC trainer.

## Files

| File | |
|------|---|
| `app.js`, `logic.js` | copied from `mobile/` without changes |
| `phrases.json` | copied from `mobile/` (built by `python mobile/tools/build_data.py`) |
| `index.html` | `mobile/index.html` with hints for desktop browsers |
| `styles.css` | `mobile/styles.css` plus the desktop sidebar (`@media (min-width: 900px)`) |
| `sw.js`, `manifest.webmanifest`, `icons/` | offline support and install, own cache name `german-phrases-web` |

After changing the mobile app or the phrases, copy `app.js`, `logic.js` and `phrases.json`
from `mobile/` again.
