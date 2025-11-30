# User Agreement

_Last updated: 2025-11-22_

## 1. Acceptance of Terms

By using Screen ASO (`aso-cli`), you agree to these terms and to any future amendments published in this document. If you do not agree, stop running the CLI or hosting related assets on a website.

## 2. Access and Eligibility

Screen ASO is distributed under the MIT License and provided "as-is". You need Python 3.10+, the dependencies listed in `requirements.txt`, and an optional browser stack via `python -m crawl4ai install-browsers`. You are free to use, modify, and distribute the Tool in accordance with the license terms. You are responsible for any third-party accounts (Apple Developer, Google Play Console) you integrate while collecting data or downloading assets.

## 3. Acceptable Use

- Do not use the Tool to collect content that you do not have permission to access.
- Respect rate limits imposed by the App Store, Play Store, and any APIs you query.
- Do not reverse engineer other vendors’ proprietary data models or siphon data for misuse.

Any automation that breaches these rules may trigger rate-limiting, legal consequences, or termination of your right to use the CLI.

## 4. Outputs and Data

Generated files live under directories such as `outputs/`, `app_store_assets/`, `aso_results/`, `app_store_search_results/`, and `play_store_search_results/`. These folders are append-only; remove or archive content yourself. Review text is automatically sanitized (see `core/privacy.py`) before it is persisted in JSON or PDF reports. You are responsible for storing, sharing, or deleting collected data in accordance with the laws applicable to your jurisdiction.

## 5. Privacy and Security

Running the Tool does not ship your local files anywhere else. We collect no telemetry or personal information besides what you paste into command-line arguments. If you configure environment variables (e.g., proxy settings) or pipeline definitions, keep them out of shared version control when they contain secrets. The redaction utilities mask emails, phone numbers, names, and credit cards to reduce exposure, but you remain responsible for sensitive outputs you choose to store or export.

## 6. Intellectual Property

The source code of Screen ASO is released under the MIT License. App metadata, review excerpts, and assets belong to their respective owners (Apple, Google, and the apps' publishers). You may use the Tool to analyze that publicly available data, but you may not claim ownership of third-party content or republish it in violation of the source platform's terms.

## 7. Disclaimers

THE TOOL IS PROVIDED WITHOUT WARRANTIES OF ANY KIND. WE DO NOT GUARANTEE THAT COLLECTED DATA IS ACCURATE, COMPLETE, OR ACCESSIBLE (App Store/Play Store availability may change). USE AT YOUR OWN RISK. 

## 8. Limitation of Liability

IN NO EVENT WILL Screen ASO OR ITS CONTRIBUTORS BE LIABLE FOR ANY INDIRECT, INCIDENTAL, CONSEQUENTIAL, OR PUNITIVE DAMAGES ARISING OUT OF YOUR USE OF THE CLI, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGES. The total liability is limited to the amount you paid (if any) to download, install, or run the Tool.

## 9. Modifications and Termination

We may update or discontinue the Tool at any time. If an update introduces breaking changes, we will document them in release notes. You may stop using the CLI whenever you like; doing so terminates your rights under this agreement.

## 10. Governing Law and Contact

These terms are governed by the laws of the jurisdiction where you run the Tool. For questions or to report abuse, email `support@screenaso.com`.
