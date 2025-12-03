# Screen ASO - App & Play Store Optimization Tool

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![CLI](https://img.shields.io/badge/CLI-Typer-orange.svg)](https://typer.tiangolo.com/)

Screen ASO is a CLI tool for App Store and Play Store research: metadata collection, review scraping, sentiment analysis, keyword extraction, asset downloads, and PDF reporting. It also offers a powerful desktop interface to accelerate your ASO workflow with metadata analysis, asset downloads, and competitor tracking all on one screen. For Turkish, see [README_TR.md](README_TR.md).

## Highlights

- **Sentiment Analysis** – English language support with aspect tagging
- **Keyword Extraction** – KeyBERT-driven semantic extraction
- **PDF Reports** – Executive summaries with redacted review excerpts
- **Asset Download** – Multi-country icons and screenshots
- **AI Assist** – Gemini/OpenRouter integration with host allowlisting
- **Auto Redaction** – Review fields masked before persistence

## Quick Start

1) Clone & env
```bash
git clone <repository-url> && cd screenaso-v1
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt && pip install -e .
```
On Windows, activate the venv with `.venv\Scripts\activate` instead of the POSIX source command.

2) Install browsers (once for scraping)
```bash
python -m playwright install
```

## Platform Support

⚠️ Tested on macOS. CLI commands run on Windows/Linux, but the desktop interface currently has issues there.

3) Sanity check
```bash
aso-cli --help
aso-cli quickref
```

### Common Commands

```bash
# Search
aso-cli quick search "fitness" --limit 10 --country US

# Keyword pipeline
aso-cli quick keyword "puzzle" --store play-store --limit 5 --reviews 50

# App audit with PDF
aso-cli quick app com.example.app --reviews 100 --report

# Asset download
aso-cli assets download 123456789 --countries US,TR,GB
```

## Output Structure

| Directory | Content |
|-----------|---------|
| `outputs/scrapes/` | Raw scraped data |
| `outputs/analyses/` | Analysis results |
| `outputs/reports/` | PDF/Markdown reports |
| `outputs/ai_results/` | AI Assist outputs |
| `app_store_assets/` | Downloaded icons/screenshots |

All outputs are slug-based (`<app-slug>/`) and append-only.

## Desktop Interface

```bash
pip install dearpygui
python gui/screenaso_app.py
```

Accelerate Your ASO Workflow With One Desktop Tool — a powerful desktop interface built for the App Store and Play Store. Metadata analysis, asset downloads, and competitor tracking all appear on one screen.

**Tabs**: Assets Download, Quick Search, Quick Keyword, Quick App, AI Assist, Results & History

## Development

```bash
# Format before PR
python -m black core/app_store core/play_store core/sentiment cli *.py

# Smoke tests
aso-cli search app-store "test" --limit 1
aso-cli scrape app 1495297747 --reviews 5
aso-cli analyze reviews outputs/scrapes/*/scrape_*.json
aso-cli report generate outputs/analyses/aso_*.json
```

Use `.env` for config: `APP_STORE_DEFAULT_COUNTRY`, `APP_STORE_DEFAULT_LANGUAGE`, `APP_STORE_HTTP_PROXY`

## Documentation

- Usage guide: `docs/USAGE_EN.md` (CLI/quick workflows, outputs, GUI)
- CLI reference: `aso-cli --help` / `aso-cli quickref`

## Contributing
- Open issues for bugs/requests with commands you ran and sample IDs if applicable.
- PRs welcome—add a brief change summary, commands you ran, and notable output files/paths.

Happy analyzing!

<a href="https://github.com/unclecode/crawl4ai">
  <img src="https://raw.githubusercontent.com/unclecode/crawl4ai/main/docs/assets/powered-by-dark.svg" alt="Powered by Crawl4AI" width="200"/>
</a>
