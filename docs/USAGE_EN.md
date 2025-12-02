# Screen ASO Usage Guide

## Setup
- Clone and prepare env:
  ```bash
  git clone <repository-url> && cd screenaso-v1
  python -m venv .venv && source .venv/bin/activate
  pip install -r requirements.txt && pip install -e .
  python -m crawl4ai install-browsers
  ```
- Config via `.env` (optional): `APP_STORE_DEFAULT_COUNTRY`, `APP_STORE_DEFAULT_LANGUAGE`, `APP_STORE_HTTP_PROXY`.

## CLI Basics
- Help/refs: `aso-cli --help`, `aso-cli quickref`.
- Common patterns:
  ```bash
  # Search a store
  aso-cli search app-store "fitness" --limit 10 --country US

  # Scrape + analyze one app
  aso-cli scrape app 1495297747 --reviews 50 --country US
  aso-cli analyze reviews outputs/scrapes/*/scrape_*.json

  # Generate report from analysis
  aso-cli report generate outputs/analyses/aso_*.json
  ```

## Quick Workflows (End-to-End)
Use predefined flows instead of manual chaining:
```bash
# Dual-store search (App Store + Play Store)
aso-cli quick search "fitness" --limit 10 --country US

# Keyword workflow (search → scrape → analyze → report)
aso-cli quick keyword "puzzle" --store play-store --limit 5 --reviews 50 --sort most_relevant --report

# Single app workflow
aso-cli quick app com.example.app --reviews 100 --language en --sort newest --report
```

## Pipeline Runs
- Copy `example_pipeline.yml` and adjust steps; run with:
  ```bash
  aso-cli pipeline run example_pipeline.yml
  ```
- Outputs land in `pipeline_results/` with per-step statuses.

## Assets Download
- App Store assets (logos/screenshots + optional PDF):
  ```bash
  aso-cli assets download 123456789 --countries US,TR,GB --output-dir app_store_assets
  ```

## Output Structure
- Append-only, slugged folders:
  - `outputs/scrapes/<app-slug>/` – raw scrapes
  - `outputs/analyses/<store>/<app-slug>/` – analyses and sentiment
  - `outputs/reports/<store>/<app-slug>/` – PDF/Markdown reports
  - `outputs/ai_results/` – AI Assist outputs
  - `app_store_assets/<app-name>/` – downloaded assets
  - `pipeline_results/` / `aso_results/` – pipeline and legacy summaries

## GUI
```bash
pip install dearpygui
python gui/screenaso_app.py
```
Tabs: Assets Download, Quick Search, Quick Keyword, Quick App, AI Assist, Results & History.

## Privacy & Masking
- Review text is sanitized via `core/privacy.py`; keep `[REDACTED]` tokens intact.
- Avoid committing large raw datasets; keep generated files under `outputs/` using slug patterns.***
