"""Search commands for Screen ASO."""

import asyncio
from datetime import datetime, timezone

import typer
from rich.console import Console

from cli.utils.output import OutputManager
from cli.utils.validation import Validator, ValidationError
from core.app_store.app_store_search import AppStoreSearchClient, AppStoreSearchError
from core.app_store.locale_utils import default_language_for_country
from core.play_store.play_store_search import PlayStoreSearchClient, PlayStoreSearchError

app = typer.Typer(help="🔍 Search apps in App Store and Google Play Store")
console = Console()
output_manager = OutputManager()
validator = Validator()


@app.command()
def app_store(
    keyword: str = typer.Argument(..., help="Search keyword (e.g., 'fitness', 'productivity', 'game')"),
    limit: int = typer.Option(10, "--limit", "-l", help="Number of results to return (default: 10, max: 50)"),
    country: str = typer.Option("US", "--country", "-c", help="Country code (US, TR, GB, DE, etc.)"),
) -> None:
    """Search apps in the Apple App Store.

    Examples:
      aso-cli search app-store "fitness" --limit 20
      aso-cli search app-store "social media" --country TR --limit 15
      aso-cli search app-store "productivity" --country GB
    """
    try:
        # Validate inputs
        keyword = validator.validate_keyword(keyword)
        limit = validator.validate_limit(limit)
        country = validator.validate_country_code(country)
        keyword_slug = output_manager.slugify(keyword)

        console.print(
            f"Searching App Store for '{keyword}' in {country} (limit: {limit})"
        )

        # Perform search
        async def search():
            client = AppStoreSearchClient()
            lang = default_language_for_country(country, "en_us")
            apps = await client.search(keyword, country=country, limit=limit, lang=lang)

            payload = {
                "query": {
                    "keyword": keyword,
                    "country": country,
                    "limit": limit,
                    "lang": lang,
                },
                "fetched_at": datetime.now(timezone.utc).isoformat(),
                "apps": apps,
            }
            return payload

        results = asyncio.run(search())

        # Save results
        filename = output_manager.get_timestamped_filename("search")
        output_path = output_manager.save_json(
            results,
            "searches",
            filename,
            store="app-store",
            slug=keyword_slug,
            context="search",
        )

        # Display summary
        if results.get("apps"):
            console.print(f"[green]✓[/green] Found {len(results['apps'])} apps")
            output_manager.print_summary(
                {
                    "Keyword": keyword,
                    "Store": "App Store",
                    "Country": country,
                    "Results": len(results["apps"]),
                    "Output": str(output_path),
                }
            )
        else:
            console.print("[yellow]No apps found[/yellow]")

    except ValidationError as e:
        console.print(f"[red]Validation error: {e}[/red]")
        raise typer.Exit(1)
    except AppStoreSearchError as e:
        console.print(f"[red]Search error: {e}[/red]")
        raise typer.Exit(1)
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")
        raise typer.Exit(1)


@app.command()
def play_store(
    keyword: str = typer.Argument(..., help="Search keyword (e.g., 'fitness', 'productivity', 'game')"),
    limit: int = typer.Option(10, "--limit", "-l", help="Number of results to return (default: 10, max: 50)"),
    country: str = typer.Option("US", "--country", "-c", help="Country code (US, TR, GB, DE, etc.)"),
    language: str = typer.Option("en", "--language", "-lang", help="Language code (en, tr, de, fr, etc.)"),
) -> None:
    """Search apps in Google Play Store.

    Examples:
      aso-cli search play-store "fitness" --limit 20 --country TR --language tr
      aso-cli search play-store "social media" --country US
      aso-cli search play-store "productivity" --language en --limit 15
    """
    try:
        # Validate inputs
        keyword = validator.validate_keyword(keyword)
        limit = validator.validate_limit(limit)
        country = validator.validate_country_code(country)
        keyword_slug = output_manager.slugify(keyword)

        console.print(
            f"Searching Play Store for '{keyword}' in {country} (limit: {limit})"
        )

        # Perform search
        async def search():
            client = PlayStoreSearchClient()
            apps = await client.search(
                keyword, country=country, language=language, limit=limit
            )

            payload = {
                "query": {
                    "keyword": keyword,
                    "country": country,
                    "limit": limit,
                    "language": language,
                },
                "fetched_at": datetime.now(timezone.utc).isoformat(),
                "apps": apps,
            }
            return payload

        results = asyncio.run(search())

        # Save results
        filename = output_manager.get_timestamped_filename("search")
        output_path = output_manager.save_json(
            results,
            "searches",
            filename,
            store="play-store",
            slug=keyword_slug,
            context="search",
        )

        # Display summary
        if results.get("apps"):
            console.print(f"[green]✓[/green] Found {len(results['apps'])} apps")
            output_manager.print_summary(
                {
                    "Keyword": keyword,
                    "Store": "Play Store",
                    "Country": country,
                    "Results": len(results["apps"]),
                    "Output": str(output_path),
                }
            )
        else:
            console.print("[yellow]No apps found[/yellow]")

    except ValidationError as e:
        console.print(f"[red]Validation error: {e}[/red]")
        raise typer.Exit(1)
    except PlayStoreSearchError as e:
        console.print(f"[red]Search error: {e}[/red]")
        raise typer.Exit(1)
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")
        raise typer.Exit(1)
