# Repository Guidelines

## Project Structure & Module Organization
- CLI entrypoint: `cli/main.py` (Typer). Subcommands live in `cli/commands/` with helpers in `cli/utils/`.
- Core logic: scrapers in `core/app_store/` and `core/play_store/`; analysis and sentiment in `core/analysis/` and `core/sentiment/`; PDF reporting in `core/pdf_report_generator.py`; privacy helpers in `core/privacy.py`.
- Desktop GUI: `gui/screenaso_app.py` (Dear PyGui). User/legal docs sit in `docs/`.
- Data artifacts: append runs under `outputs/`, `aso_results/`, `pipeline_results/`, `app_store_assets/`, and store search dumps. Use slugged paths like `outputs/scrapes/<app-slug>/...`; never delete history. Models/cache stay under `models/`.
- Templates/config: `example_pipeline.yml`; add new presets alongside it. Keep generated files out of `docs/` unless meant for users.

## Build, Test, and Development Commands
- Create env: `python -m venv .venv && source .venv/bin/activate`.
- Install deps: `pip install -r requirements.txt && pip install -e .`.
- Browser drivers for scraping: `python -m crawl4ai install-browsers`.
- CLI smoke checks (small limits): `aso-cli --help`, `aso-cli quickref`, `aso-cli search app-store "test" --limit 1`, `aso-cli scrape app 1495297747 --reviews 5`, `aso-cli analyze reviews outputs/scrapes/*/scrape_*.json`, `aso-cli report generate outputs/analyses/aso_*.json`.
- GUI: `pip install dearpygui && python gui/screenaso_app.py`.
- Format before pushing: `python -m black core/app_store core/play_store core/sentiment cli *.py`.

## Coding Style & Naming Conventions
- Python 3.10+, 4-space indents, type hints, snake_case for functions/vars, PascalCase for classes.
- Typer options use kebab-case flags; keep console output Rich-friendly and reuse existing logging helpers.
- Preserve `[REDACTED]` tokens and route new user text through `core/privacy.py`.

## Testing Guidelines
- No full suite yet; rely on the smoke commands above after changes.
- Keep outputs lightweight and under slugged folders in `outputs/`; extend `.gitignore` if new cache dirs appear.
- Avoid committing large datasets; include sample IDs/sources when relevant.

## Commit & Pull Request Guidelines
- Commits: short imperative subjects aligned with current history (e.g., “Add play store scrape limit”).
- PRs: list commands run, affected output paths, new flags/config, and link issues/tasks. Include screenshots or gifs for `gui/` updates.
- Document sample IDs/sources and avoid committing new large datasets.

## Security & Configuration Tips
- Never hardcode API keys, proxies, or store credentials. Use `.env` vars such as `APP_STORE_DEFAULT_COUNTRY`, `APP_STORE_DEFAULT_LANGUAGE`, and `APP_STORE_HTTP_PROXY`.
- Keep PII masking intact in scrapers/analyzers (JSON/PDF/Markdown).***
