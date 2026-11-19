# VisionTouch landing page

A single static page: `index.html`, `style.css`, `main.js` and `assets/`. No build step, no external requests. All URLs are relative, so it works from the file system and from a sub-path such as `https://<user>.github.io/visiontouch/`.

## Preview locally

Open `index.html` in a browser, or serve the folder:

```sh
python3 -m http.server 8000 --directory site    # then open http://localhost:8000/
```

`screenshots/` holds headless renders at 1440×900, 768×1024 and 390×844 (and dark mode); they are not used by the page.

## Deploy

1. Once the repository is public, open **Settings → Pages** and set **Source** to **GitHub Actions**.
2. Run the **Pages** workflow (`.github/workflows/pages.yml`) from the Actions tab. It also runs by itself whenever a release is published.

The download buttons point to `https://github.com/jweaker/visiontouch/releases/latest/download/<archive>`, so they only work after the first tagged release (`v*`, see `packaging/README.md`) has published its archives. The Open Graph tags assume the page lives at `https://jweaker.github.io/visiontouch/`; change `og:url` and `og:image` in `index.html` if it is served elsewhere.

## Updating

- Numbers on the page are copied by hand from `docs/report.md`. When `eval/fill_report.py` changes the report, update the **Measured results** and **How it works** sections to match.
- Images in `assets/` are resized WebP copies of `web/screenshots/` and crops of `docs/figures/pipeline_good.png` and `calibration.png`. `assets/og.png` (1200×630) is a render of the page's own hero.
- Fonts are the ones the app bundles (Bricolage Grotesque, Atkinson Hyperlegible), under the SIL Open Font License; the licence texts sit next to them in `assets/`.
