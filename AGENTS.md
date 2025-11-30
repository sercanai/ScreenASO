# Repository Guidelines

Quick guide for Screen ASO contributors. Keep changes small, log the commands you run, and prefer append-only outputs.

## Project Structure & Modules
- `cli/main.py` is the Typer entrypoint; subcommands live under `cli/commands/` with shared helpers in `cli/utils/`.
- Core logic sits in `core/`: `app_store/` and `play_store/` scrapers, `analysis/` and `sentiment/` pipelines, `pdf_report_generator.py`, and `privacy.py`.
- `gui/` hosts the Dear PyGui desktop app (`gui/screenaso_app.py`); `docs/` holds legal/user-facing copy.
- Data artifacts: `outputs/` (scrapes/analyses/reports), `app_store_assets/`, store search dumps, `aso_results/`, and `pipeline_results/`. Use slugged paths such as `outputs/scrapes/<app-slug>/...` and avoid deleting history.
- `example_pipeline.yml` is the template for custom pipelines; add new presets beside it.

## Build, Test, and Development Commands
- Environment: `python -m venv .venv && source .venv/bin/activate`
- Install: `pip install -r requirements.txt && pip install -e .`
- Browser drivers for scraping: `python -m crawl4ai install-browsers`
- CLI checks: `aso-cli --help` and `aso-cli quickref`; GUI: `pip install dearpygui && python gui/screenaso_app.py`
- Format before pushing: `python -m black core/app_store core/play_store core/sentiment cli *.py`

## Coding Style & Naming Conventions
- Python 3.10+, 4-space indents, type hints, and module-level docstrings for new files.
- snake_case for functions/variables, PascalCase for classes, and concise Typer option names (kebab-case flags).
- Keep console output Rich-friendly; reuse existing console helpers instead of ad-hoc prints.
- Treat redaction tokens (`[REDACTED]`) as immutable—preserve or extend them when writing new outputs.

## Testing Guidelines
- No formal test suite yet; run lightweight smoke checks:
  - `aso-cli search app-store "test" --limit 1`
  - `aso-cli scrape app 1495297747 --reviews 5`
  - `aso-cli analyze reviews outputs/scrapes/*/scrape_*.json`
  - `aso-cli report generate outputs/analyses/aso_*.json`
- Use small limits; keep generated files under `outputs/` using the slug pattern.

## Commit & Pull Request Guidelines
- Use short imperative commit subjects, mirroring current history.
- PRs should list commands run, affected output paths, and new configuration flags; add screenshots or gifs for `gui/` changes.
- Link issues/tasks, note sample IDs or sources, and avoid committing large datasets—extend `.gitignore` if a new cache folder is introduced.

## Security & Configuration Tips
- Do not hardcode API keys, proxies, or store credentials; prefer `.env` keys such as `APP_STORE_DEFAULT_COUNTRY`, `APP_STORE_DEFAULT_LANGUAGE`, and `APP_STORE_HTTP_PROXY`.
- Preserve PII masking: new scrapers or analyzers must funnel user text through `core/privacy.py` before writing JSON/PDF/Markdown outputs.
