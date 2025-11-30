"""Quick workflow commands for Screen ASO."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import typer
from rich.console import Console

from cli.commands.pipeline import execute_search_step
from cli.commands import analyze as analyze_commands
from cli.utils.output import OutputManager
from cli.utils.validation import ValidationError, Validator

app = typer.Typer(help="⚡️ Quick start workflows (search, scrape, analyze, report)")
console = Console()
output_manager = OutputManager()
validator = Validator()

SORT_CHOICES = ["most_relevant", "newest", "rating"]
STORE_CHOICES = ["app-store", "play-store"]


@app.command()
def search(
    keyword: str = typer.Argument(..., help="Keyword to search in both stores"),
    limit: int = typer.Option(10, "--limit", "-l", help="Number of results per store"),
    country: str = typer.Option("US", "--country", "-c", help="Country code"),
    language: str = typer.Option("en", "--language", "-lang", help="Play Store language"),
) -> None:
    """Search the same keyword on both stores and store the combined result."""
    try:
        keyword = validator.validate_keyword(keyword)
        limit = validator.validate_limit(limit)
        country = validator.validate_country_code(country)
        keyword_slug = output_manager.slugify(keyword)

        console.print(f"[cyan]Searching App Store & Play Store for '{keyword}' ({country})[/cyan]")

        app_store_path = Path(
            execute_search_step(
                {
                    "store": "app-store",
                    "keyword": keyword,
                    "limit": limit,
                    "country": country,
                },
                None,
            )
        )
        play_store_path = Path(
            execute_search_step(
                {
                    "store": "play-store",
                    "keyword": keyword,
                    "limit": limit,
                    "country": country,
                    "language": language,
                },
                None,
            )
        )

        app_store_results = output_manager.load_json(str(app_store_path))
        play_store_results = output_manager.load_json(str(play_store_path))

        combined = {
            "keyword": keyword,
            "country": country,
            "limit": limit,
            "play_language": language,
            "fetched_at": app_store_results.get("fetched_at"),
            "app_store": app_store_results,
            "play_store": play_store_results,
        }

        filename = output_manager.get_timestamped_filename("quick_search")
        combined_path = output_manager.save_json(
            combined,
            "searches",
            filename,
            store="multi-store",
            slug=keyword_slug,
            context="quick-search",
        )

        output_manager.print_summary(
            {
                "Keyword": keyword,
                "Country": country,
                "Results/App Store": len(app_store_results.get("apps", [])),
                "Results/Play Store": len(play_store_results.get("apps", [])),
                "Combined Output": str(combined_path),
            }
        )
        console.print(
            f"[dim]Individual files: {app_store_path} (App Store), {play_store_path} (Play Store)[/dim]"
        )

    except ValidationError as e:
        console.print(f"[red]Validation error: {e}[/red]")
        raise typer.Exit(1)
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")
        raise typer.Exit(1)


@app.command()
def keyword(
    keyword: str = typer.Argument(..., help="Search keyword for the workflow"),
    store: str = typer.Option("play-store", "--store", "-s", help="Target store"),
    limit: int = typer.Option(3, "--limit", "-l", help="How many apps to analyze"),
    reviews: int = typer.Option(50, "--reviews", "-r", help="Reviews per app"),
    country: str = typer.Option("US", "--country", "-c", help="Country code"),
    language: str = typer.Option("en", "--language", "-lang", help="Language (Play Store)"),
    sort: str = typer.Option("most_relevant", "--sort", "-S", help="Play Store review sort order"),
    report: bool = typer.Option(True, "--report/--no-report", help="Generate PDF reports"),
) -> None:
    """Run search → scrape → analyze → report for the given keyword and store."""
    try:
        store_normalized = store.lower()
        if store_normalized not in STORE_CHOICES:
            raise ValidationError(f"store must be one of: {', '.join(STORE_CHOICES)}")
        sort_normalized = sort.lower()
        if sort_normalized not in SORT_CHOICES:
            raise ValidationError(f"sort must be one of: {', '.join(SORT_CHOICES)}")

        keyword = validator.validate_keyword(keyword)
        limit = validator.validate_limit(limit)
        reviews = validator.validate_limit(reviews)
        country = validator.validate_country_code(country)
        keyword_slug = output_manager.slugify(keyword)

        console.print(
            f"[cyan]Running quick workflow for '{keyword}' on {store_normalized} (limit={limit}, reviews={reviews})[/cyan]"
        )

        search_params = {
            "store": store_normalized,
            "keyword": keyword,
            "limit": limit,
            "country": country,
        }
        if store_normalized == "play-store":
            search_params["language"] = language

        search_output = Path(execute_search_step(search_params, None))
        search_payload = output_manager.load_json(str(search_output))

        apps = search_payload.get("apps") or []
        if not apps:
            console.print("[yellow]No apps found for the provided keyword[/yellow]")
            raise typer.Exit()

        analyzed_records = []
        selected_apps = apps[:limit]
        for idx, app_entry in enumerate(selected_apps, 1):
            app_id_value = app_entry.get("app_id") or app_entry.get("id")
            if not app_id_value:
                continue
            app_id_str = str(app_id_value)
            console.print(f"\n[magenta]Analyzing {idx}/{len(selected_apps)}:[/magenta] {app_entry.get('app_name') or app_id_str}")
            result = analyze_commands.aso(
                app_id=app_id_str,
                reviews=reviews,
                country=country,
                language=language if store_normalized == "play-store" else "en",
                sort=sort_normalized,
                report=report,
                report_output=None,
            )
            if isinstance(result, dict):
                analyzed_records.append(
                    {
                        "app_id": app_id_str,
                        "app_name": app_entry.get("app_name") or app_entry.get("name"),
                        "analysis_path": str(result.get("analysis_path")),
                        "report_path": (
                            str(result.get("report_path")) if result.get("report_path") else None
                        ),
                    }
                )

        summary_payload = {
            "keyword": keyword,
            "store": store_normalized,
            "country": country,
            "limit": limit,
            "reviews": reviews,
            "sort": sort_normalized,
            "apps": analyzed_records,
        }
        summary_filename = output_manager.get_timestamped_filename("quick_keyword")
        summary_output = output_manager.save_json(
            summary_payload,
            "analyses",
            summary_filename,
            store=store_normalized,
            slug=keyword_slug,
            context="quick-workflow",
        )

        output_manager.print_summary(
            {
                "Keyword": keyword,
                "Store": store_normalized,
                "Apps Analyzed": len(analyzed_records),
                "Summary Output": str(summary_output),
                "Reports": "enabled" if report else "disabled",
            }
        )

    except ValidationError as e:
        console.print(f"[red]Validation error: {e}[/red]")
        raise typer.Exit(1)
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")
        raise typer.Exit(1)


@app.command(name="app")
def app_workflow(
    app_id: str = typer.Argument(..., help="App ID or package name"),
    reviews: int = typer.Option(50, "--reviews", "-r", help="Reviews to fetch"),
    country: str = typer.Option("US", "--country", "-c", help="Country code"),
    language: Optional[str] = typer.Option(
        None,
        "--language",
        "-lang",
        help="Language hint (Play Store) e.g. en, tr",
    ),
    sort: str = typer.Option("most_relevant", "--sort", "-S", help="Play Store review sort order"),
    report: bool = typer.Option(True, "--report/--no-report", help="Generate PDF report"),
) -> None:
    """Scrape, analyze, and report for a single app ID."""
    try:
        sort_normalized = sort.lower()
        if sort_normalized not in SORT_CHOICES:
            raise ValidationError(f"sort must be one of: {', '.join(SORT_CHOICES)}")

        app_id = validator.validate_app_id(app_id)
        reviews = validator.validate_limit(reviews)
        country = validator.validate_country_code(country)

        console.print(
            f"[cyan]Running full workflow for {app_id} ({country}, reviews={reviews})[/cyan]"
        )

        result = analyze_commands.aso(
            app_id=app_id,
            reviews=reviews,
            country=country,
            language=language or "en",
            sort=sort_normalized,
            report=report,
            report_output=None,
        )

        output_manager.print_summary(
            {
                "App ID": app_id,
                "Analysis Output": str(result.get("analysis_path")) if result else "unknown",
                "Report": (
                    str(result.get("report_path")) if result and result.get("report_path") else "disabled"
                ),
            }
        )

    except ValidationError as e:
        console.print(f"[red]Validation error: {e}[/red]")
        raise typer.Exit(1)
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")
        raise typer.Exit(1)
