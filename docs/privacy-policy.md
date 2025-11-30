# Privacy Policy

_Last updated: 2025-11-30_

## 1. Introduction

Screen ASO (the "Tool") is an open-source App Store Optimization assistant built on top of a Typer-based CLI. The Tool runs entirely on your machine and does not send any of your inputs, outputs, or environment to remote servers unless you explicitly configure such integrations. This policy explains how the Tool collects, processes, and protects data when you run commands such as `search`, `collect`, `analyze`, `assets download`, or `report generate`.

As an open-source project, Screen ASO is developed transparently and community contributions are welcome. The source code is available for review at our repository.

## 2. Data We Collect

- **Review and metadata payloads:** When you collect data from apps or reviews, the Tool downloads publicly available metadata and reviews from the App Store and Play Store. These responses may contain reviewers' names, titles, or bodies that reference personal identifiers; we never share them and we do not augment them with other data sources.
- **Usage context:** The only persistent configuration values are those you provide via command-line arguments, environment variables (e.g., `APP_STORE_DEFAULT_COUNTRY`, `APP_STORE_HTTP_PROXY`), or pipeline YAML files. Inputs like app identifiers, search keywords, country/language filters, and limits are stored locally within your generated output files.
- **No accounts:** There are no user accounts, logins, or tracking cookies tied to the Tool itself.
- **No telemetry:** The Tool does not collect any usage statistics, crash reports, or telemetry data. All processing happens locally on your machine.

## 3. How We Use Your Data

All data remains local by default. The Tool uses collected reviews and metadata to:

- hydrate pipelines (`outputs/data/…`, `outputs/analyses/…`, `outputs/reports/…`);
- power sentiment, keyword, and metadata analysis;
- render PDF or Markdown reports for offline review;
- download app store assets into `app_store_assets/` and write raw search artifacts into `app_store_search_results/` / `play_store_search_results/`.

Nothing is transmitted externally without your explicit automation (for example, piping generated PDFs or JSON to other services).

## 4. Data Sanitization and Security

Before persisting review text, the Tool automatically redacts personally identifiable information (PII) from titles and bodies using `core/privacy.py`. It first attempts to run the Presidio analyzer/anonymizer stack and falls back to regular expression masking (emails, phone numbers, credit cards). After collecting data, review `title`/`body` fields become placeholders such as `[REDACTED]_TITLE` and `[REDACTED]_BODY` when stored under `outputs/` or when embedded in PDF reports.

We encourage you to store any remaining sensitive data in secure directories. Output folders are append-only by design; avoid deleting, and archive older data if needed.

## 5. Data Retention

Retention is under your control. The Tool does not delete any artifacts it has written, so you manage life-cycle by removing or archiving files yourself. When running pipelines, consider pruning or archiving the `outputs/`, `aso_results/`, `app_store_assets/`, and other folders if storage becomes a concern.

## 6. Your Rights and Controls

Since the Tool runs locally:

- You can view, move, or delete any generated files at any time.
- If you wish to stop collection, simply halt the CLI and do not re-run the command.
- The source code is available for inspection at our repository.
- For questions about how your local data is used, please open an issue on our GitHub repository.

## 7. Third-Party Services

The Tool collects publicly available data from third-party platforms (Apple App Store and Google Play Store). These services are bound by their own terms of use; if you use the Tool to download or analyze data, you remain responsible for complying with those platforms' rules.

**Your Responsibilities:**
- Ensure you have the right to collect and analyze the data you gather
- Respect rate limits and robots.txt directives of third-party platforms
- Comply with Apple App Store Review Guidelines and Google Play Developer Distribution Agreement
- Do not use collected data for purposes that violate platform policies (e.g., competitive intelligence that breaches terms)
- You are solely liable for any violations of third-party terms of service; Screen ASO provides the tool but does not authorize or endorse any specific use case

## 8. Open Source and Community

Screen ASO is an open-source project licensed under the MIT License. Community contributions are welcome and encouraged. For information about contributing, please see our CONTRIBUTING.md file in the repository.

## 9. Changes to This Policy

We may update this policy to reflect changes in the Tool. Whenever possible, we will version new releases and call out the updated date at the top of this document. All changes to this policy will be made transparently through our public repository.

## 10. Contact

For questions about this privacy policy, please:
- Open an issue on our GitHub repository
- Start a discussion in our GitHub Discussions
- Review our source code for technical details

We do not provide direct email support for this open-source project.
