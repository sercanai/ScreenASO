"""Pipeline commands for Screen ASO."""

import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

import typer
import yaml
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn

from cli.utils.output import OutputManager
from cli.utils.reporting import generate_pdf_report
from cli.utils.scraping import scrape_app_data
from cli.utils.validation import ValidationError, Validator
from core.privacy import sanitize_reviews_for_output

app = typer.Typer(help="Run analysis pipelines")
console = Console()
output_manager = OutputManager()
validator = Validator()


@app.command()
def run(
    config: str = typer.Argument(..., help="Pipeline configuration file (YAML)"),
    output_dir: str = typer.Option(
        "./pipeline_results", "--output-dir", "-o", help="Output directory"
    ),
) -> None:
    """Run a pipeline from YAML configuration."""
    try:
        # Validate config file
        config_path = Path(config)
        if not config_path.exists():
            raise ValidationError(f"Config file not found: {config}")

        console.print(f"\n[bold cyan]Running Pipeline[/bold cyan]")
        console.print(f"Config: {config}\n")

        # Load pipeline config
        with open(config_path, "r") as f:
            pipeline_config = yaml.safe_load(f)

        pipeline_name = pipeline_config.get("name", "Unnamed Pipeline")
        steps = pipeline_config.get("steps", [])

        if not steps:
            console.print("[yellow]No steps defined in pipeline[/yellow]")
            return

        console.print(f"[bold]Pipeline:[/bold] {pipeline_name}")
        console.print(f"[bold]Steps:[/bold] {len(steps)}\n")

        # Execute pipeline
        results = []
        previous_output = None

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console,
        ) as progress:
            task = progress.add_task(
                f"Executing {len(steps)} steps...", total=len(steps)
            )

            for idx, step in enumerate(steps, 1):
                step_name = step.get("name", f"Step {idx}")
                command = step.get("command")
                params = step.get("params", {})

                progress.console.print(
                    f"\n[cyan]Step {idx}/{len(steps)}:[/cyan] {step_name}"
                )
                progress.console.print(f"Command: {command}")

                try:
                    # Execute step based on command
                    if command == "search":
                        result = execute_search_step(params, previous_output)
                    elif command == "scrape":
                        result = execute_scrape_step(params, previous_output)
                    elif command == "analyze":
                        result = execute_analyze_step(params, previous_output)
                    elif command == "report":
                        result = execute_report_step(params, previous_output)
                    else:
                        progress.console.print(
                            f"[yellow]Unknown command: {command}[/yellow]"
                        )
                        result = None

                    if result:
                        results.append(
                            {
                                "step": step_name,
                                "command": command,
                                "output": result,
                                "status": "success",
                            }
                        )
                        previous_output = result
                        progress.console.print(f"[green]✓[/green] Step completed")
                    else:
                        results.append(
                            {
                                "step": step_name,
                                "command": command,
                                "status": "failed",
                            }
                        )
                        progress.console.print(f"[red]✗[/red] Step failed")

                except Exception as e:
                    progress.console.print(f"[red]✗ Error: {e}[/red]")
                    results.append(
                        {
                            "step": step_name,
                            "command": command,
                            "error": str(e),
                            "status": "error",
                        }
                    )

                progress.advance(task)

        # Save pipeline results
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)

        pipeline_result = {
            "pipeline_name": pipeline_name,
            "config_file": str(config_path),
            "steps": results,
            "total_steps": len(steps),
            "successful_steps": sum(
                1 for r in results if r.get("status") == "success"
            ),
        }

        result_file = output_path / f"{pipeline_name.lower().replace(' ', '_')}_result.json"
        with result_file.open("w", encoding="utf-8") as f:
            json.dump(pipeline_result, f, indent=2, ensure_ascii=False)
            f.write("\n")

        # Summary
        console.print(f"\n[bold green]✓ Pipeline completed![/bold green]\n")
        output_manager.print_summary(
            {
                "Pipeline": pipeline_name,
                "Total Steps": len(steps),
                "Successful": pipeline_result["successful_steps"],
                "Failed": len(steps) - pipeline_result["successful_steps"],
                "Results": str(result_file),
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


def execute_search_step(params: Dict[str, Any], previous_output: Any) -> str:
    """Execute a search step."""
    from core.app_store.app_store_search import AppStoreSearchClient
    from core.play_store.play_store_search import PlayStoreSearchClient

    store = params.get("store", "app-store")
    keyword = params.get("keyword")
    limit = params.get("limit", 10)
    country = params.get("country", "US")
    language = params.get("language")

    if not keyword:
        raise ValueError("keyword is required for search step")

    keyword_slug = output_manager.slugify(keyword)
    store_slug = output_manager.infer_store_slug(store=store)

    async def search():
        metadata_language = language
        if store == "app-store":
            client = AppStoreSearchClient()
            from core.app_store.locale_utils import default_language_for_country

            lang = default_language_for_country(country, "en_us")
            apps = await client.search(keyword, country=country, limit=limit, lang=lang)
            metadata_language = lang
        else:
            client = PlayStoreSearchClient()
            used_language = language or "en"
            apps = await client.search(
                keyword,
                country=country,
                limit=limit,
                language=used_language,
            )
            metadata_language = used_language

        # Save results
        filename = output_manager.get_timestamped_filename("search")
        output_path = output_manager.save_json(
            {
                "apps": apps,
                "keyword": keyword,
                "store": store,
                "country": country,
                "limit": limit,
                "language": metadata_language,
            },
            "searches",
            filename,
            store=store_slug or store,
            slug=keyword_slug,
            context="search",
        )
        return str(output_path)

    return asyncio.run(search())


def execute_scrape_step(params: Dict[str, Any], previous_output: Any) -> str:
    """Execute a scrape step."""
    app_candidates: List[str] = []
    previous_data: Dict[str, Any] = {}

    if previous_output and Path(previous_output).exists():
        previous_data = output_manager.load_json(previous_output)
        apps = previous_data.get("apps") or []
        for app in apps:
            app_id = app.get("app_id") or app.get("id")
            if app_id:
                app_candidates.append(str(app_id))

    if not app_candidates:
        manual_app = params.get("app_id")
        if manual_app:
            app_candidates.append(str(manual_app))

    if not app_candidates:
        raise ValueError("No app IDs found. Provide 'app_id' or a previous search output.")

    limit = params.get("limit")
    if isinstance(limit, int) and limit > 0:
        app_candidates = app_candidates[:limit]

    country = (
        params.get("country")
        or previous_data.get("query", {}).get("country")
        or "US"
    )
    reviews = params.get("reviews", 50)
    language = params.get("language") or previous_data.get("query", {}).get("language")
    reviews_language = params.get("reviews_language")
    reviews_sort = params.get("reviews_sort", "newest")

    results: List[Dict[str, Any]] = []
    unique_stores: set[str] = set()
    failures: List[str] = []
    for candidate in app_candidates:
        try:
            store_label, payload = scrape_app_data(
                candidate,
                country=country,
                reviews=reviews,
                language=language,
                reviews_language=reviews_language,
                reviews_sort=reviews_sort,
            )
            payload.setdefault("store", store_label)
            results.append(payload)
            store_slug = output_manager.infer_store_slug(store=store_label)
            if store_slug:
                unique_stores.add(store_slug)
        except Exception as exc:  # pragma: no cover
            failures.append(f"{candidate}: {exc}")

    if not results:
        raise RuntimeError(
            "Scrape step failed for all apps"
            + (f" ({'; '.join(failures)})" if failures else "")
        )

    batch_slug = output_manager.slugify(
        previous_data.get("keyword")
        or previous_data.get("query", {}).get("keyword")
        or "batch"
    )
    batch_store_slug = (
        next(iter(unique_stores))
        if len(unique_stores) == 1
        else ("multi-store" if unique_stores else None)
    )
    scraped_at = datetime.now(timezone.utc).isoformat()
    if len(results) == 1:
        single_store_slug = output_manager.infer_store_slug(app=results[0])
        single_slug = output_manager.derive_app_slug(app=results[0])
        output_payload = {
            "source_file": previous_output,
            "scraped_at": scraped_at,
            "app": results[0],
        }
        filename = output_manager.get_timestamped_filename("scrape")
        output_path = output_manager.save_json(
            sanitize_reviews_for_output(output_payload),
            "scrapes",
            filename,
            store=single_store_slug,
            slug=single_slug,
            context="scrape",
        )
    else:
        output_payload = {
            "source_file": previous_output,
            "scraped_at": scraped_at,
            "query": {
                "app_ids": app_candidates,
                "country": country,
                "reviews": reviews,
                "language": language,
                "reviews_sort": reviews_sort,
            },
            "apps": results,
        }
        filename = output_manager.get_timestamped_filename("batch_scrape")
        if failures:
            output_payload["failed_apps"] = failures
        output_path = output_manager.save_json(
            sanitize_reviews_for_output(output_payload),
            "scrapes",
            filename,
            store=batch_store_slug,
            slug=batch_slug,
            context="batch-scrape",
        )
    for app_result in results:
        single_payload = {
            "source_file": previous_output,
            "scraped_at": scraped_at,
            "app": app_result,
        }
        single_store = output_manager.infer_store_slug(app=app_result)
        single_slug = output_manager.derive_app_slug(app=app_result)
        single_filename = output_manager.get_timestamped_filename("scrape")
        output_manager.save_json(
            sanitize_reviews_for_output(single_payload),
            "scrapes",
            single_filename,
            store=single_store,
            slug=single_slug,
            context="scrape",
        )
    return str(output_path)


def execute_analyze_step(params: Dict[str, Any], previous_output: Any) -> str:
    """Execute an analyze step."""
    from core.sentiment.pipeline import SentimentAnalyzer

    # Use previous output if available
    input_file = previous_output or params.get("input")
    if not input_file:
        raise ValueError("input is required for analyze step")

    analyze_type = params.get("type", "reviews")

    data = output_manager.load_json(input_file)
    analyzer = SentimentAnalyzer()
    analysis_timestamp = datetime.now(timezone.utc).isoformat()

    if analyze_type == "reviews":
        # Analyze reviews
        apps = data.get("apps", [data.get("app")])
        results = []
        stores_encountered: set[str] = set()
        aggregate_slug = output_manager.slugify(Path(input_file).stem)

        for app in apps:
            if not app:
                continue

            reviews = app.get("reviews", [])
            sentiments = []

            for review in reviews:
                text = review.get("review_text") or review.get("text", "")
                if text:
                    sentiment = analyzer.analyze_text(text)
                    sentiments.append(sentiment.get("label", "neutral"))

            from collections import Counter

            sentiment_counts = Counter(sentiments)
            summary = {
                "app_name": app.get("app_name") or app.get("name"),
                "sentiment": dict(sentiment_counts),
            }
            results.append(summary)
            single_payload = {
                "analyzed_at": analysis_timestamp,
                "app": summary,
            }
            single_store_slug = output_manager.infer_store_slug(app=app)
            if single_store_slug:
                stores_encountered.add(single_store_slug)
            single_slug = output_manager.derive_app_slug(app=app)
            single_filename = output_manager.get_timestamped_filename("analysis")
            output_manager.save_json(
                sanitize_reviews_for_output(single_payload),
                "analyses",
                single_filename,
                store=single_store_slug,
                slug=single_slug,
                context="analysis",
            )

        # Save results
        filename = output_manager.get_timestamped_filename("analysis")
        aggregate_store = (
            next(iter(stores_encountered))
            if len(stores_encountered) == 1
            else ("multi-store" if stores_encountered else None)
        )
        output_path = output_manager.save_json(
            sanitize_reviews_for_output(
                {"analyzed_at": analysis_timestamp, "results": results}
            ),
            "analyses",
            filename,
            store=aggregate_store,
            slug=aggregate_slug,
            context="analysis",
        )
        return str(output_path)

    return input_file


def execute_report_step(params: Dict[str, Any], previous_output: Any) -> str:
    """Execute a report step."""
    # Use previous output if available
    input_file = previous_output or params.get("input")
    if not input_file:
        raise ValueError("input is required for report step")

    specified_output = params.get("output")
    title = params.get("title", "Pipeline Report")

    data = output_manager.load_json(input_file)
    if specified_output:
        output_file = Path(specified_output)
    else:
        first_app = data.get("app") if isinstance(data.get("app"), dict) else None
        if not first_app:
            for key in ("apps", "results"):
                collection = data.get(key)
                if isinstance(collection, list) and collection:
                    candidate = collection[0]
                    if isinstance(candidate, dict) and isinstance(candidate.get("app"), dict):
                        first_app = candidate["app"]
                    elif isinstance(candidate, dict):
                        first_app = candidate
                    break
        store_slug = output_manager.infer_store_slug(app=first_app)
        slug = output_manager.derive_slug_from_payload(data, default="pipeline")
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        base_name = OutputManager._slugify(title) or "pipeline-report"
        output_file = output_manager.build_output_path(
            "reports",
            f"{base_name}_{timestamp}.pdf",
            store=store_slug,
            slug=slug,
            context="report",
        )

    generate_pdf_report(data, output_file, title=title)

    return str(output_file)


@app.command()
def create(
    name: str = typer.Argument(..., help="Pipeline name"),
    output: str = typer.Option(
        "pipeline.yml", "--output", "-o", help="Output YAML file"
    ),
) -> None:
    """Create a new pipeline configuration template."""
    template = {
        "name": name,
        "description": "Pipeline description",
        "steps": [
            {
                "name": "Search Apps",
                "command": "search",
                "params": {
                    "store": "app-store",
                    "keyword": "fitness",
                    "limit": 10,
                    "country": "US",
                },
            },
            {
                "name": "Scrape Reviews",
                "command": "scrape",
                "params": {"reviews": 50, "country": "US"},
            },
            {
                "name": "Analyze Sentiment",
                "command": "analyze",
                "params": {"type": "reviews"},
            },
            {
                "name": "Generate Report",
                "command": "report",
                "params": {"output": "report.pdf", "title": name},
            },
        ],
    }

    output_path = Path(output)
    with open(output_path, "w") as f:
        yaml.dump(template, f, default_flow_style=False, sort_keys=False)

    console.print(f"[green]✓[/green] Pipeline template created: {output}")
    console.print(f"\nEdit the file and run: [cyan]aso-cli pipeline run {output}[/cyan]")
