"""Analyze commands for Screen ASO."""

import asyncio
import re
from collections import Counter
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import typer
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.table import Table

from cli.utils.metadata_reporting import build_metadata_keyword_report
from cli.utils.output import OutputManager
from cli.utils.reporting import generate_pdf_report
from cli.utils.scraping import scrape_app_data
from cli.utils.validation import ValidationError, Validator
from core.analysis import MetadataKeywordAnalyzer, MetadataKeywordRequest
from core.privacy import sanitize_reviews_for_output, strip_redacted_text
from core.sentiment.pipeline import SentimentAnalyzer

app = typer.Typer(help="📊 Analyze app data with sentiment analysis and insights")
console = Console()
output_manager = OutputManager()
validator = Validator()


class StoreOption(str, Enum):
    APP_STORE = "app-store"
    PLAY_STORE = "play-store"
    BOTH = "both"


def _slugify_keyword(value: str) -> str:
    slug = output_manager.slugify(value)
    return slug if slug and slug != "app" else "keyword"


def _render_keyword_table(title: str, keywords: Dict[str, int], *, limit: int = 10) -> None:
    if not keywords:
        console.print(f"[yellow]{title}: veri yok[/yellow]")
        return

    table = Table(title=title, show_header=True)
    table.add_column("Keyword", style="cyan")
    table.add_column("Frekans", justify="right", style="green")

    for keyword, count in list(keywords.items())[:limit]:
        table.add_row(keyword, str(count))

    console.print(table)


def _extract_review_text(review: Dict[str, Any]) -> Tuple[str, str]:
    """Return sanitized body/title content stripped of placeholder markers."""
    body_raw = (
        review.get("review_text")
        or review.get("body")
        or review.get("text")
        or ""
    )
    title_raw = review.get("title") or ""
    return strip_redacted_text(body_raw), strip_redacted_text(title_raw)


def _collect_review_metrics(
    source: Dict[str, Any],
    *,
    sentiments: List[str],
    review_types: List[str],
) -> int:
    """Append sentiment/type stats from an analysis payload."""
    label = source.get("sentiment_label")
    if not label:
        return 0
    sentiments.append(label)
    review_types.append(source.get("review_type", "general_feedback"))
    return 1 if source.get("needs_reply") else 0


@app.command()
def reviews(
    input: str = typer.Argument(..., help="Input JSON file with review data (from scrape command)"),
    detailed: bool = typer.Option(False, "--detailed", "-d", help="Show detailed analysis with examples"),
) -> None:
    """Analyze reviews with sentiment analysis and statistics.

    Performs sentiment analysis (positive/negative/neutral), extracts keywords,
    identifies common themes, and categorizes review types.

    Examples:
      aso-cli analyze reviews outputs/scrapes/app_123456.json
      aso-cli analyze reviews app_reviews.json --detailed
    """
    try:
        # Validate inputs
        input_file = validator.validate_file_exists(input)

        console.print(f"Analyzing reviews from {input}")

        # Load data
        data = output_manager.load_json(input_file)
        
        # Handle different data formats
        if "apps" in data and isinstance(data["apps"], list):
            apps = data["apps"]
        elif "app" in data:
            apps = [data["app"]]
        elif "reviews" in data:
            # This is a single app data (like from aso_analyzer.py)
            apps = [data]
        else:
            apps = []

        if not apps:
            console.print("[yellow]No apps found in input file[/yellow]")
            return

        analysis_timestamp = datetime.now(timezone.utc).isoformat()

        analysis_timestamp = datetime.now(timezone.utc).isoformat()

        # Initialize sentiment analyzer (ReviewEnricher)
        from core.sentiment.pipeline import ReviewEnricher
        enricher = ReviewEnricher()

        # Analyze each app
        analysis_results = []
        stores_seen: set[str] = set()
        aggregate_slug = output_manager.slugify(Path(input).stem or "reviews")

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console,
        ) as progress:
            task = progress.add_task(f"Analyzing {len(apps)} apps...", total=len(apps))

            for app in apps:
                app_name = app.get("app_name") or app.get("name", "Unknown")
                reviews = app.get("reviews", [])

                if not reviews:
                    progress.console.print(
                        f"[yellow]No reviews for {app_name}[/yellow]"
                    )
                    progress.advance(task)
                    continue

                # Enrich reviews with full sentiment analysis
                enriched_reviews = []
                sentiments = []
                ratings = []
                review_types = []
                needs_reply_count = 0

                for review in reviews:
                    # Get review text and metadata
                    body, title = _extract_review_text(review)
                    rating = review.get("rating") or review.get("user_rating")

                    if body or title:
                        analysis_body = body or title
                        analysis_title = title if body else None
                        # Full sentiment analysis using ReviewEnricher
                        enriched = enricher.analyze_review(
                            body=analysis_body,
                            title=analysis_title,
                            rating=float(rating) if rating else None,
                        )
                        
                        # Merge with original review
                        review_copy = review.copy()
                        review_copy.update(enriched)
                        enriched_reviews.append(review_copy)
                        
                        # Collect stats
                        needs_reply_count += _collect_review_metrics(
                            enriched,
                            sentiments=sentiments,
                            review_types=review_types,
                        )
                    else:
                        review_copy = review.copy()
                        enriched_reviews.append(review_copy)
                        needs_reply_count += _collect_review_metrics(
                            review_copy,
                            sentiments=sentiments,
                            review_types=review_types,
                        )

                    if rating:
                        ratings.append(float(rating))

                # Calculate statistics
                sentiment_counts = Counter(sentiments)
                type_counts = Counter(review_types)
                
                app_analysis = {
                    "app_name": app_name,
                    "app_id": app.get("app_id") or app.get("id"),
                    "total_reviews": len(reviews),
                    "sentiment": {
                        "positive": sentiment_counts.get("positive", 0),
                        "negative": sentiment_counts.get("negative", 0),
                        "neutral": sentiment_counts.get("neutral", 0),
                        "positive_ratio": (
                            sentiment_counts.get("positive", 0) / len(sentiments)
                            if sentiments
                            else 0
                        ),
                    },
                    "review_types": dict(type_counts),
                    "needs_reply": needs_reply_count,
                    "ratings": {
                        "average": sum(ratings) / len(ratings) if ratings else 0,
                        "count": len(ratings),
                    },
                    "review_stats": {
                        "total_analyzed": len(sentiments),
                    },
                    "enriched_reviews": enriched_reviews,  # Include enriched reviews
                }

                analysis_results.append(app_analysis)
                single_payload = {
                    "input_file": input,
                    "analyzed_at": analysis_timestamp,
                    "app": app_analysis,
                }
                store_slug = output_manager.infer_store_slug(app=app)
                if store_slug:
                    stores_seen.add(store_slug)
                single_slug = output_manager.derive_app_slug(
                    app=app, app_name=app_analysis["app_name"], app_id=app_analysis.get("app_id")
                )
                single_filename = output_manager.get_timestamped_filename("reviews_analysis")
                output_manager.save_json(
                    sanitize_reviews_for_output(single_payload),
                    "analyses",
                    single_filename,
                    store=store_slug,
                    slug=single_slug,
                    context="reviews",
                )
                progress.advance(task)

        # Save results
        results = {
            "input_file": input,
            "analyzed_at": analysis_timestamp,
            "total_apps": len(apps),
            "apps": analysis_results,
        }

        filename = output_manager.get_timestamped_filename("reviews_analysis")
        aggregate_store = (
            next(iter(stores_seen))
            if len(stores_seen) == 1
            else ("multi-store" if stores_seen else None)
        )
        output_path = output_manager.save_json(
            sanitize_reviews_for_output(results),
            "analyses",
            filename,
            store=aggregate_store,
            slug=aggregate_slug,
            context="reviews",
        )

        # Display results
        console.print(f"\n[green]✓[/green] Analysis completed")

        if detailed:
            # Show detailed table
            table = Table(title="Review Analysis Results")
            table.add_column("App Name", style="cyan")
            table.add_column("Reviews", justify="right")
            table.add_column("Positive", justify="right", style="green")
            table.add_column("Negative", justify="right", style="red")
            table.add_column("Neutral", justify="right", style="yellow")
            table.add_column("Avg Rating", justify="right")

            for app_result in analysis_results:
                table.add_row(
                    app_result["app_name"][:30],
                    str(app_result["total_reviews"]),
                    str(app_result["sentiment"]["positive"]),
                    str(app_result["sentiment"]["negative"]),
                    str(app_result["sentiment"]["neutral"]),
                    f"{app_result['ratings']['average']:.2f}",
                )

            console.print(table)

        # Summary
        total_reviews = sum(app["total_reviews"] for app in analysis_results)
        total_positive = sum(app["sentiment"]["positive"] for app in analysis_results)
        total_negative = sum(app["sentiment"]["negative"] for app in analysis_results)

        output_manager.print_summary(
            {
                "Total Apps": len(analysis_results),
                "Total Reviews": total_reviews,
                "Positive Reviews": total_positive,
                "Negative Reviews": total_negative,
                "Output": str(output_path),
            }
        )

    except ValidationError as e:
        console.print(f"[red]Validation error: {e}[/red]")
        raise typer.Exit(1)
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")
        raise typer.Exit(1)


@app.command()
def keywords(
    input: str = typer.Argument(..., help="Input JSON file with app data"),
    top_n: int = typer.Option(50, "--top", "-n", help="Number of top keywords to show"),
) -> None:
    """Extract and analyze keywords from app descriptions and reviews."""
    try:
        # Validate inputs
        input_file = validator.validate_file_exists(input)

        console.print(f"Analyzing keywords from {input}")
        analysis_timestamp = datetime.now(timezone.utc).isoformat()

        # Load data
        data = output_manager.load_json(input_file)
        
        # Handle both single app and multi-app formats
        if "app" in data:
            apps = [data["app"]]
        elif "apps" in data:
            apps = data.get("apps", [])
        else:
            # Assume the data itself is an app
            apps = [data]

        if not apps:
            console.print("[yellow]No apps found in input file[/yellow]")
            return

        # Import keyword analysis functions
        from core.analysis import (
            analyze_description,
            analyze_reviews,
            compare_keywords,
        )

        # Extract keywords from each app
        keyword_results = []
        keyword_stores: set[str] = set()
        aggregate_slug = output_manager.slugify(Path(input).stem or "keywords")

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console,
        ) as progress:
            task = progress.add_task(
                f"Extracting keywords from {len(apps)} apps...", total=len(apps)
            )

            for app in apps:
                app_name = app.get("app_name") or app.get("name", "Unknown")
                app_id = app.get("app_id") or app.get("id", "unknown")

                # Analyze description
                description = app.get("description") or app.get("app_description", "")
                desc_analysis = analyze_description(description) if description else {
                    "top_keywords": {},
                    "bigrams": {},
                    "trigrams": {},
                }

                # Analyze reviews
                reviews = app.get("reviews", [])
                review_analysis = analyze_reviews(reviews) if reviews else {
                    "top_keywords": {},
                    "bigrams": {},
                    "trigrams": {},
                    "cooccurrence": {},
                }

                # Compare keywords
                comparison = compare_keywords(
                    desc_analysis["top_keywords"], review_analysis["top_keywords"]
                )

                single_result = {
                    "app_name": app_name,
                    "app_id": app_id,
                    "analysis": {
                        "description": desc_analysis,
                        "reviews": review_analysis,
                        "comparison": comparison,
                    },
                }
                keyword_results.append(single_result)
                single_payload = {
                    "input_file": input,
                    "analyzed_at": analysis_timestamp,
                    "app": single_result,
                }
                store_slug = output_manager.infer_store_slug(app=app)
                if store_slug:
                    keyword_stores.add(store_slug)
                single_slug = output_manager.derive_app_slug(
                    app=app, app_name=app_name, app_id=app_id
                )
                single_filename = output_manager.get_timestamped_filename("keyword_analysis")
                output_manager.save_json(
                    sanitize_reviews_for_output(single_payload),
                    "analyses",
                    single_filename,
                    store=store_slug,
                    slug=single_slug,
                    context="keywords",
                )

                progress.advance(task)

        # Save results
        results = {
            "input_file": input,
            "analyzed_at": analysis_timestamp,
            "total_apps": len(apps),
            "apps": keyword_results,
        }

        filename = output_manager.get_timestamped_filename("keyword_analysis")
        aggregate_store = (
            next(iter(keyword_stores))
            if len(keyword_stores) == 1
            else ("multi-store" if keyword_stores else None)
        )
        output_path = output_manager.save_json(
            sanitize_reviews_for_output(results),
            "analyses",
            filename,
            store=aggregate_store,
            slug=aggregate_slug,
            context="keywords",
        )

        # Display results
        console.print(f"\n[green]✓[/green] Keyword analysis completed")

        # Show top keywords for each app
        for app_result in keyword_results:
            console.print(f"\n[cyan]{app_result['app_name']}[/cyan]")
            
            # Description keywords
            desc_keywords = list(app_result["analysis"]["description"]["top_keywords"].items())[:top_n]
            if desc_keywords:
                console.print("\n[bold]Description Keywords:[/bold]")
                table = Table(show_header=True, header_style="bold magenta")
                table.add_column("Keyword", style="green")
                table.add_column("Count", justify="right")

                for kw, count in desc_keywords[:10]:  # Show top 10
                    table.add_row(kw, str(count))

                console.print(table)

            # Review keywords
            review_keywords = list(app_result["analysis"]["reviews"]["top_keywords"].items())[:top_n]
            if review_keywords:
                console.print("\n[bold]Review Keywords:[/bold]")
                table = Table(show_header=True, header_style="bold magenta")
                table.add_column("Keyword", style="green")
                table.add_column("Count", justify="right")

                for kw, count in review_keywords[:10]:  # Show top 10
                    table.add_row(kw, str(count))

                console.print(table)

            # Common keywords
            common_keywords = list(app_result["analysis"]["comparison"]["common_keywords"].items())
            if common_keywords:
                console.print("\n[bold]Common Keywords (Desc + Reviews):[/bold]")
                console.print(", ".join([kw for kw, _ in common_keywords[:5]]))

        output_manager.print_summary(
            {
                "Total Apps": len(keyword_results),
                "Keywords per App": top_n,
                "Output": str(output_path),
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


@app.command("metadata-keywords")
def metadata_keywords(
    keyword: str = typer.Argument(..., help="Arama anahtar kelimesi (örn. 'ai image')"),
    limit: int = typer.Option(20, "--limit", "-l", help="Her store için analiz edilecek uygulama sayısı"),
    store: StoreOption = typer.Option(
        StoreOption.BOTH,
        "--store",
        "-s",
        case_sensitive=False,
        help="Hangi store'da çalışılacağını seç (app-store, play-store, both)",
    ),
    app_store_country: str = typer.Option("US", "--app-store-country", help="App Store ülke kodu"),
    app_store_language: Optional[str] = typer.Option(
        None, "--app-store-language", help="App Store dilini ez (örn. en, tr)"
    ),
    play_store_country: str = typer.Option("US", "--play-store-country", help="Play Store ülke kodu"),
    play_store_language: Optional[str] = typer.Option(
        None,
        "--play-store-language",
        help="Play Store dili (hl parametresi, boş bırakılırsa ülkeye göre otomatik)",
    ),
    concurrency: int = typer.Option(
        4,
        "--concurrency",
        min=1,
        max=10,
        help="Aynı anda çekilecek metadata istek sayısı",
    ),
    report: bool = typer.Option(
        True,
        "--report/--no-report",
        help="Markdown formatında ek rapor üret",
    ),
    report_top: int = typer.Option(
        15,
        "--report-top",
        min=3,
        max=30,
        help="Rapor tablolarında gösterilecek maksimum kelime sayısı",
    ),
) -> None:
    """Sadece uygulama adı ve açıklamasından keyword çıkaran özel analiz."""

    try:
        keyword = validator.validate_keyword(keyword)
        limit = validator.validate_limit(limit)
        app_store_country = validator.validate_country_code(app_store_country)
        play_store_country = validator.validate_country_code(play_store_country)

        include_app_store = store in (StoreOption.BOTH, StoreOption.APP_STORE)
        include_play_store = store in (StoreOption.BOTH, StoreOption.PLAY_STORE)

        console.print(
            f"[bold]Metadata keyword analizi[/bold] başlatılıyor: '{keyword}' ({store.value})"
        )

        analyzer = MetadataKeywordAnalyzer(concurrency=concurrency)
        request = MetadataKeywordRequest(
            keyword=keyword,
            limit=limit,
            include_app_store=include_app_store,
            include_play_store=include_play_store,
            app_store_country=app_store_country,
            app_store_language=app_store_language,
            play_store_country=play_store_country,
            play_store_language=play_store_language,
        )

        result = asyncio.run(analyzer.run(request))

        slug_suffix = (
            "both"
            if include_app_store and include_play_store
            else ("app-store" if include_app_store else "play-store")
        )
        slug = f"{_slugify_keyword(keyword)}-{slug_suffix}-metadata"
        store_for_output = (
            "multi-store"
            if include_app_store and include_play_store
            else ("app-store" if include_app_store else "play-store")
        )
        filename = output_manager.get_timestamped_filename("metadata_keywords")
        output_path = output_manager.save_json(
            result,
            "analyses",
            filename,
            store=store_for_output,
            slug=slug,
            context="metadata-keywords",
        )

        console.print(f"[green]✓[/green] Analiz tamamlandı ve kaydedildi: {output_path}")

        report_path: Optional[Path] = None
        if report:
            markdown = build_metadata_keyword_report(result, top_n=report_top)
            report_filename = output_manager.get_timestamped_filename(
                "metadata_keywords_report", "md"
            )
            report_path = output_manager.save_text(
                markdown,
                "reports",
                report_filename,
                store=store_for_output,
                slug=slug,
                context="metadata-keywords",
            )
            console.print(
                f"[green]✓[/green] Markdown raporu kaydedildi: {report_path}"
            )

        for store_key, payload in result.get("stores", {}).items():
            store_label = "App Store" if store_key == "app_store" else "Play Store"
            stats = payload.get("stats", {})
            console.print(
                f"\n[bold]{store_label}[/bold]: {stats.get('apps_found', 0)} uygulama, "
                f"{stats.get('descriptions_collected', 0)} açıklama"
            )
            keyword_analysis = payload.get("keyword_analysis", {})
            _render_keyword_table(
                f"{store_label} - İsim Keywordleri",
                keyword_analysis.get("names", {}).get("top_keywords", {}),
            )
            _render_keyword_table(
                f"{store_label} - Açıklama Keywordleri",
                keyword_analysis.get("descriptions", {}).get("top_keywords", {}),
            )

        combined = result.get("combined_keyword_analysis", {})
        console.print("\n[bold]Kombine Keyword Özeti[/bold]")
        _render_keyword_table(
            "Kombine İsim Keywordleri",
            combined.get("names", {}).get("top_keywords", {}),
        )
        _render_keyword_table(
            "Kombine Açıklama Keywordleri",
            combined.get("descriptions", {}).get("top_keywords", {}),
        )

        global_stats = result.get("global_stats", {})
        output_manager.print_summary(
            {
                "Keyword": keyword,
                "Stores": ", ".join(result.get("query", {}).get("stores", [])),
                "Toplam App": global_stats.get("total_apps", 0),
                "İsim Keywordleri": len(
                    combined.get("names", {}).get("top_keywords", {})
                ),
                "Açıklama Keywordleri": len(
                    combined.get("descriptions", {}).get("top_keywords", {})
                ),
                "Output": str(output_path),
                "Report": str(report_path) if report_path else "-",
            }
        )

    except ValidationError as e:
        console.print(f"[red]Validation error: {e}[/red]")
        raise typer.Exit(1)
    except Exception as e:  # pragma: no cover - defensive
        console.print(f"[red]Error: {e}[/red]")
        raise typer.Exit(1)


@app.command()
def compare(
    app1: str = typer.Argument(..., help="First app JSON file"),
    app2: str = typer.Argument(..., help="Second app JSON file"),
) -> None:
    """Compare two apps side by side."""
    try:
        # Validate inputs
        app1_file = validator.validate_file_exists(app1)
        app2_file = validator.validate_file_exists(app2)

        console.print(f"Comparing {app1} and {app2}")

        # Load both files
        data1 = output_manager.load_json(app1_file)
        data2 = output_manager.load_json(app2_file)

        # Extract app data (handle both single app and multi-app formats)
        app1_data = data1.get("app") or (
            data1.get("apps", [])[0] if data1.get("apps") else {}
        )
        app2_data = data2.get("app") or (
            data2.get("apps", [])[0] if data2.get("apps") else {}
        )

        if not app1_data or not app2_data:
            console.print("[red]Could not extract app data from files[/red]")
            raise typer.Exit(1)

        # Initialize sentiment analyzer
        analyzer = SentimentAnalyzer()

        # Analyze both apps
        def analyze_app(app_data):
            reviews = app_data.get("reviews", [])
            sentiments = []
            ratings = []

            for review in reviews:
                text = review.get("review_text") or review.get("text", "")
                rating = review.get("rating") or review.get("user_rating")

                if text:
                    sentiment = analyzer.analyze_text(text)
                    sentiments.append(sentiment.get("label", "neutral"))

                if rating:
                    ratings.append(float(rating))

            sentiment_counts = Counter(sentiments)

            return {
                "name": app_data.get("app_name") or app_data.get("name", "Unknown"),
                "id": app_data.get("app_id") or app_data.get("id"),
                "total_reviews": len(reviews),
                "rating": app_data.get("user_rating") or app_data.get("rating", 0),
                "rating_count": app_data.get("user_rating_count")
                or app_data.get("rating_count", 0),
                "sentiment": {
                    "positive": sentiment_counts.get("positive", 0),
                    "negative": sentiment_counts.get("negative", 0),
                    "neutral": sentiment_counts.get("neutral", 0),
                },
                "avg_review_rating": (
                    sum(ratings) / len(ratings) if ratings else 0
                ),
            }

        console.print("\n[cyan]Analyzing apps...[/cyan]")
        app1_analysis = analyze_app(app1_data)
        app2_analysis = analyze_app(app2_data)

        # Create comparison table
        table = Table(title="App Comparison", show_header=True)
        table.add_column("Metric", style="cyan")
        table.add_column(app1_analysis["name"][:30], style="green")
        table.add_column(app2_analysis["name"][:30], style="yellow")

        # Add rows
        table.add_row("App ID", str(app1_analysis["id"]), str(app2_analysis["id"]))
        table.add_row(
            "Store Rating",
            f"{app1_analysis['rating']:.2f}",
            f"{app2_analysis['rating']:.2f}",
        )
        table.add_row(
            "Rating Count",
            f"{app1_analysis['rating_count']:,}",
            f"{app2_analysis['rating_count']:,}",
        )
        table.add_row(
            "Reviews Analyzed",
            str(app1_analysis["total_reviews"]),
            str(app2_analysis["total_reviews"]),
        )
        table.add_row(
            "Positive Reviews",
            str(app1_analysis["sentiment"]["positive"]),
            str(app2_analysis["sentiment"]["positive"]),
        )
        table.add_row(
            "Negative Reviews",
            str(app1_analysis["sentiment"]["negative"]),
            str(app2_analysis["sentiment"]["negative"]),
        )
        table.add_row(
            "Neutral Reviews",
            str(app1_analysis["sentiment"]["neutral"]),
            str(app2_analysis["sentiment"]["neutral"]),
        )
        table.add_row(
            "Avg Review Rating",
            f"{app1_analysis['avg_review_rating']:.2f}",
            f"{app2_analysis['avg_review_rating']:.2f}",
        )

        console.print(table)

        # Save comparison results
        results = {
            "compared_at": datetime.now(timezone.utc).isoformat(),
            "app1": {
                "file": app1,
                "analysis": app1_analysis,
            },
            "app2": {
                "file": app2,
                "analysis": app2_analysis,
            },
        }

        filename = output_manager.get_timestamped_filename("comparison")
        slug1 = output_manager.derive_app_slug(app=app1_data)
        slug2 = output_manager.derive_app_slug(app=app2_data)
        combined_slug = OutputManager._slugify(f"{slug1}-vs-{slug2}")
        store1 = output_manager.infer_store_slug(app=app1_data)
        store2 = output_manager.infer_store_slug(app=app2_data)
        comparison_store = (
            store1 if store1 and store1 == store2 else ("multi-store" if store1 or store2 else None)
        )
        output_path = output_manager.save_json(
            sanitize_reviews_for_output(results),
            "analyses",
            filename,
            store=comparison_store,
            slug=combined_slug,
            context="comparison",
        )

        console.print(f"\n[green]✓[/green] Comparison completed")
        console.print(f"Results saved to: {output_path}")

    except ValidationError as e:
        console.print(f"[red]Validation error: {e}[/red]")
        raise typer.Exit(1)
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")
        raise typer.Exit(1)


@app.command()
def aso(
    app_id: str = typer.Argument(..., help="App ID (e.g., com.example.app or 123456)"),
    reviews: int = typer.Option(
        50, "--reviews", "-r", help="Number of reviews to analyze"
    ),
    country: str = typer.Option("US", "--country", "-c", help="Country code"),
    language: str = typer.Option(
        "en", "--language", "-lang", help="Language code (Play Store metadata/reviews)"
    ),
    sort: str = typer.Option(
        "newest",
        "--sort",
        "-S",
        help="Play Store review sort order (most_relevant, newest, rating)",
    ),
    report: bool = typer.Option(
        False, "--report", help="Generate PDF report after the analysis"
    ),
    report_output: Optional[str] = typer.Option(
        None, "--report-output", help="Custom PDF output path"
    ),
) -> Optional[dict]:
    """Run the full Screen ASO pipeline (scrape + analyze)."""
    try:
        # Validate inputs
        app_id = validator.validate_app_id(app_id)
        reviews = validator.validate_limit(reviews)
        country = validator.validate_country_code(country)
        sort_normalized = sort.lower()
        if sort_normalized not in {"most_relevant", "newest", "rating"}:
            raise ValidationError("Sort must be one of: most_relevant, newest, rating")

        console.print(
            f"\n[bold cyan]Starting Full Screen ASO Pipeline[/bold cyan]"
        )
        console.print(f"App ID: {app_id}")
        console.print(f"Reviews: {reviews}")
        console.print(f"Country: {country}\n")

        # Step 1: Scrape app data
        console.print("[bold]Step 1/3:[/bold] Scraping app data...")

        store_label, app_data = scrape_app_data(
            app_id,
            country=country,
            reviews=reviews,
            language=language,
            reviews_language=language,
            reviews_sort=sort_normalized,
        )
        console.print(f"[blue]Detected: {store_label}[/blue]")

        console.print("[green]✓[/green] App data scraped successfully\n")
        store_slug = output_manager.infer_store_slug(store=store_label)
        app_slug = output_manager.derive_app_slug(
            app=app_data, app_id=app_id, store=store_slug
        )

        # Step 2: Sentiment Analysis
        console.print("[bold]Step 2/3:[/bold] Analyzing sentiment...")

        from core.sentiment.pipeline import ReviewEnricher
        enricher = ReviewEnricher()
        app_reviews = app_data.get("reviews", [])

        enriched_reviews = []
        sentiments = []
        ratings = []
        review_types = []
        needs_reply_count = 0

        for review in app_reviews:
            body, title = _extract_review_text(review)
            rating = review.get("rating") or review.get("user_rating")

            if body or title:
                analysis_body = body or title
                analysis_title = title if body else None
                # Full sentiment analysis
                enriched = enricher.analyze_review(
                    body=analysis_body,
                    title=analysis_title,
                    rating=float(rating) if rating else None,
                )
                
                # Merge with original
                review_copy = review.copy()
                review_copy.update(enriched)
                enriched_reviews.append(review_copy)
                
                needs_reply_count += _collect_review_metrics(
                    enriched,
                    sentiments=sentiments,
                    review_types=review_types,
                )
            else:
                review_copy = review.copy()
                enriched_reviews.append(review_copy)
                needs_reply_count += _collect_review_metrics(
                    review_copy,
                    sentiments=sentiments,
                    review_types=review_types,
                )

            if rating:
                ratings.append(float(rating))

        sentiment_counts = Counter(sentiments)
        type_counts = Counter(review_types)
        console.print("[green]✓[/green] Sentiment analysis completed\n")

        # Step 3: Keyword Extraction
        console.print("[bold]Step 3/3:[/bold] Extracting keywords...")

        from core.analysis import (
            analyze_description,
            analyze_reviews as analyze_review_keywords,
            compare_keywords,
        )

        # Analyze description
        description = app_data.get("description") or app_data.get("app_description", "")
        desc_analysis = analyze_description(description) if description else {
            "top_keywords": {},
            "bigrams": {},
            "trigrams": {},
        }

        # Analyze reviews
        review_analysis = analyze_review_keywords(enriched_reviews) if enriched_reviews else {
            "top_keywords": {},
            "bigrams": {},
            "trigrams": {},
            "cooccurrence": {},
        }

        # Compare keywords
        keyword_comparison = compare_keywords(
            desc_analysis["top_keywords"], review_analysis["top_keywords"]
        )

        console.print("[green]✓[/green] Keyword extraction completed\n")

        desc_keyword_items = list(desc_analysis["top_keywords"].items())
        review_keyword_items = list(review_analysis["top_keywords"].items())

        # Compile results
        results = {
            "app_id": app_id,
            "country": country,
            "analyzed_at": datetime.now(timezone.utc).isoformat(),
            "app_info": {
                "name": app_data.get("app_name") or app_data.get("name", "Unknown"),
                "developer": app_data.get("developer") or app_data.get("developer_name"),
                "rating": app_data.get("user_rating")
                or app_data.get("rating")
                or app_data.get("rating_value", 0),
                "rating_count": app_data.get("user_rating_count")
                or app_data.get("rating_count")
                or app_data.get("ratingCount", 0),
            },
            "review_analysis": {
                "total_reviews": len(app_reviews),
                "sentiment": {
                    "positive": sentiment_counts.get("positive", 0),
                    "negative": sentiment_counts.get("negative", 0),
                    "neutral": sentiment_counts.get("neutral", 0),
                    "positive_ratio": (
                        sentiment_counts.get("positive", 0) / len(sentiments)
                        if sentiments
                        else 0
                    ),
                },
                "review_types": dict(type_counts),
                "needs_reply": needs_reply_count,
                "avg_rating": sum(ratings) / len(ratings) if ratings else 0,
            },
            "keyword_analysis": {
                "description": desc_analysis,
                "reviews": review_analysis,
                "comparison": keyword_comparison,
            },
            "enriched_reviews": enriched_reviews,
            "raw_data": app_data,
        }

        # Save results
        filename = output_manager.get_timestamped_filename(f"aso_{app_id}")
        output_path = output_manager.save_json(
            sanitize_reviews_for_output(results),
            "analyses",
            filename,
            store=store_slug,
            slug=app_slug,
            context="aso",
        )

        # Display summary
        console.print("[bold green]✓ Screen ASO analysis completed![/bold green]\n")

        # Summary table
        summary_table = Table(title="Screen ASO Analysis Summary", show_header=False)
        summary_table.add_column("Metric", style="cyan")
        summary_table.add_column("Value", style="green")

        summary_table.add_row("App Name", results["app_info"]["name"])
        summary_table.add_row("App ID", app_id)
        summary_table.add_row("Store Rating", f"{results['app_info']['rating']:.2f}")
        summary_table.add_row(
            "Rating Count", f"{results['app_info']['rating_count']:,}"
        )
        summary_table.add_row("Reviews Analyzed", str(len(app_reviews)))
        summary_table.add_row(
            "Positive Reviews", str(sentiment_counts.get("positive", 0))
        )
        summary_table.add_row(
            "Negative Reviews", str(sentiment_counts.get("negative", 0))
        )
        summary_table.add_row(
            "Positive Ratio",
            f"{results['review_analysis']['sentiment']['positive_ratio']:.1%}",
        )
        summary_table.add_row("Keywords (Desc)", str(len(desc_keyword_items)))
        summary_table.add_row("Keywords (Reviews)", str(len(review_keyword_items)))
        summary_table.add_row("Review Types", str(len(type_counts)))
        summary_table.add_row("Needs Reply", str(needs_reply_count))

        console.print(summary_table)

        # Top keywords
        if desc_keyword_items:
            console.print("\n[bold]Top Keywords (Description):[/bold]")
            kw_table = Table(show_header=True)
            kw_table.add_column("Keyword", style="green")
            kw_table.add_column("Count", justify="right")

            for kw, count in desc_keyword_items[:10]:
                kw_table.add_row(kw, str(count))

            console.print(kw_table)
        
        if review_keyword_items:
            console.print("\n[bold]Top Keywords (Reviews):[/bold]")
            kw_table = Table(show_header=True)
            kw_table.add_column("Keyword", style="green")
            kw_table.add_column("Count", justify="right")

            for kw, count in review_keyword_items[:10]:
                kw_table.add_row(kw, str(count))

            console.print(kw_table)

        console.print(f"\n[cyan]Full results saved to:[/cyan] {output_path}")

        report_path: Optional[Path] = None
        if report:
            if report_output:
                report_path = Path(report_output)
            else:
                report_filename = f"{Path(output_path).stem}.pdf"
                report_path = output_manager.build_output_path(
                    "reports",
                    report_filename,
                    store=store_slug,
                    slug=app_slug,
                    context="aso",
                )
            generate_pdf_report(results, report_path)
            console.print(f"[green]✓[/green] PDF report generated: {report_path}")

        return {
            "analysis_path": output_path,
            "report_path": report_path,
            "app_slug": app_slug,
        }

    except ValidationError as e:
        console.print(f"[red]Validation error: {e}[/red]")
        raise typer.Exit(1)
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")
        import traceback

        console.print(traceback.format_exc())
        raise typer.Exit(1)
