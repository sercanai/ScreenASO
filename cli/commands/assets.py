"""Assets commands for Screen ASO."""

import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Optional

import typer
from rich.console import Console

from cli.utils.output import OutputManager
from cli.utils.validation import ValidationError, Validator
from core.app_store.download_app_assets import (
    AppAssetDownloader,
    create_pdf_report,
)

app = typer.Typer(help="Download app assets")
console = Console()
output_manager = OutputManager()
validator = Validator()


@app.command()
def download(
    app_id: str = typer.Argument(..., help="App ID to download assets for"),
    output_dir: str = typer.Option(
        "./app_store_assets", "--output-dir", "-o", help="Output directory"
    ),
    countries: str = typer.Option(
        "us,tr,jp", "--countries", "-c", help="Comma-separated country codes"
    ),
    languages: Optional[str] = typer.Option(
        None,
        "--languages",
        "-l",
        help="Optional country-language overrides (e.g. 'tr:tr-tr,jp:ja-jp')",
    ),
    no_pdf: bool = typer.Option(
        False, "--no-pdf", help="Skip PDF report generation", show_default=False
    ),
) -> None:
    """Download App Store logos/screenshots for multiple countries and generate summary reports."""
    try:
        app_id = validator.validate_app_id(app_id)
        country_list = [c.strip().lower() for c in countries.split(",") if c.strip()]
        if not country_list:
            raise ValidationError("At least one country code is required")

        language_map: Dict[str, str] = {}
        if languages:
            for pair in languages.split(","):
                if ":" in pair:
                    country, lang = pair.split(":", 1)
                    if country.strip() and lang.strip():
                        language_map[country.strip().lower()] = lang.strip()

        console.print(f"\n[bold cyan]Downloading assets for app {app_id}[/bold cyan]")
        console.print(f"Countries: {', '.join(c.upper() for c in country_list)}")
        console.print(f"Output: {output_dir}\n")

        output_path = Path(output_dir)
        downloader = AppAssetDownloader(output_path)

        async def orchestrate():
            primary_country = country_list[0]
            metadata = await downloader.get_app_metadata(app_id, primary_country)
            app_name = metadata.get("trackName") if metadata else None
            if not app_name:
                app_name = f"app_{app_id}"
            results = await downloader.download_all_countries(
                app_id,
                app_name,
                country_list,
                language_map if language_map else None,
            )
            return app_name, metadata, results

        app_name, metadata, results = asyncio.run(orchestrate())
        if not results:
            console.print("[red]No assets were downloaded[/red]")
            raise typer.Exit(1)

        total_screenshots = sum(r.get("screenshot_count", 0) for r in results)
        total_logos = sum(1 for r in results if r.get("logo_path"))

        app_dir = output_path / app_name
        app_dir.mkdir(parents=True, exist_ok=True)

        app_info = {}
        if metadata:
            app_info = {
                "developer": metadata.get("artistName"),
                "bundle_id": metadata.get("bundleId"),
                "version": metadata.get("version"),
                "price": metadata.get("formattedPrice", "Free"),
                "rating": metadata.get("averageUserRating"),
                "rating_count": metadata.get("userRatingCount"),
                "primary_genre": metadata.get("primaryGenreName"),
                "release_date": metadata.get("releaseDate"),
            }

        report_data = {
            "app_id": app_id,
            "app_name": app_name,
            "app_info": app_info,
            "downloaded_at": datetime.now(timezone.utc).isoformat(),
            "summary": {
                "total_countries": len(results),
                "total_logos_downloaded": total_logos,
                "total_screenshots_downloaded": total_screenshots,
            },
            "countries": results,
        }

        json_output = app_dir / "download_report.json"
        with json_output.open("w", encoding="utf-8") as f:
            json.dump(report_data, f, indent=2, ensure_ascii=False)
            f.write("\n")
        console.print(f"[green]✓[/green] JSON report saved to {json_output}")

        pdf_output: Optional[Path] = None
        if not no_pdf:
            pdf_output = app_dir / "assets_report.pdf"
            try:
                create_pdf_report(app_name, app_id, results, pdf_output, app_info)
                console.print(f"[green]✓[/green] PDF report saved to {pdf_output}")
            except Exception as exc:
                console.print(f"[yellow]PDF creation failed:[/yellow] {exc}")
                pdf_output = None

        console.print(f"\n[bold green]✓ Asset download completed![/bold green]\n")

        output_manager.print_summary(
            {
                "App ID": app_id,
                "App Name": app_name,
                "Countries": len(results),
                "Logos Downloaded": total_logos,
                "Screenshots Downloaded": total_screenshots,
                "Output Directory": str(app_dir),
                "Report JSON": str(json_output),
                "Report PDF": str(pdf_output) if pdf_output else "Skipped",
            }
        )

    except ValidationError as e:
        console.print(f"[red]Validation error: {e}[/red]")
        raise typer.Exit(1)
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")
        import traceback

        console.print(traceback.format_exc())
        raise typer.Exit(1)
