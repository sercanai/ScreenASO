# Repository Guidelines

## Project Structure & Module Organization
- CLI entrypoint: `cli/main.py` (Typer). Subcommands live in `cli/commands/` with helpers in `cli/utils/`.
- Core logic: `core/app_store/`, `core/play_store/` (scrapers), `core/analysis/`, `core/sentiment/`, `core/pdf_report_generator.py`, and `core/privacy.py`.
- Desktop GUI: `gui/screenaso_app.py` (Dear PyGui). User/legal copy sits in `docs/`.
- Data artifacts: `outputs/`, `aso_results/`, `pipeline_results/`, `app_store_assets/`, and store search dumps. Use slugged paths like `outputs/scrapes/<app-slug>/...`; append new runs, do not delete history.
- Templates/config: `example_pipeline.yml` (add new presets alongside). Models/cache live under `models/`.

## Build, Test, and Development Commands
- Create env: `python -m venv .venv && source .venv/bin/activate`
- Install: `pip install -r requirements.txt && pip install -e .`
- Browser drivers (scraping): `python -m crawl4ai install-browsers`
- CLI quick check: `aso-cli --help` and `aso-cli quickref`
- Smoke runs (small limits): `aso-cli search app-store "test" --limit 1`, `aso-cli scrape app 1495297747 --reviews 5`, `aso-cli analyze reviews outputs/scrapes/*/scrape_*.json`, `aso-cli report generate outputs/analyses/aso_*.json`
- GUI: `pip install dearpygui && python gui/screenaso_app.py`

## Coding Style & Naming Conventions
- Python 3.10+, 4-space indents, type hints, snake_case functions/vars, PascalCase classes. Concise Typer options use kebab-case flags.
- Keep console output Rich-friendly; reuse existing console/logging helpers rather than ad-hoc prints.
- Format before pushing: `python -m black core/app_store core/play_store core/sentiment cli *.py`
- Preserve `[REDACTED]` tokens and other PII masking; route new user text through `core/privacy.py`.

## Testing Guidelines
- No full test suite yet; rely on the smoke commands above after changes. Keep generated files under `outputs/` using slug patterns.
- Keep tests/data lightweight; avoid committing large datasets. Extend `.gitignore` if a new cache folder appears.

## Commit & Pull Request Guidelines
- Use short imperative commit subjects similar to current history.
- PRs should list commands run, affected output paths, new flags/config, and link issues/tasks. Add screenshots or gifs for `gui/` updates.
- Note sample IDs/sources; avoid committing new large datasets.

## Security & Configuration Tips
- Never hardcode API keys, proxies, or store credentials. Prefer `.env` vars such as `APP_STORE_DEFAULT_COUNTRY`, `APP_STORE_DEFAULT_LANGUAGE`, and `APP_STORE_HTTP_PROXY`.
- Preserve PII masking in any new scraper/analyzer output (JSON/PDF/Markdown).
