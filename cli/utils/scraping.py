"""Shared scraping helpers for CLI commands."""

from __future__ import annotations

import asyncio
from typing import Any, Dict, Tuple, List, Optional

from core.app_store.app_store_simple_scraper import (
    AppStoreScraper as SimpleAppStoreScraper,
)
from core.play_store.play_store_scraper import PlayStoreScraper
from core.sentiment.pipeline import ReviewEnricher
from core.privacy import strip_redacted_text


def is_play_store_app(app_id: str) -> bool:
    """Detect store type from the identifier."""
    return "." in str(app_id) and not str(app_id).isdigit()


_APP_STORE_REVIEW_ENRICHER: Optional[ReviewEnricher] = None


def _get_app_store_enricher() -> ReviewEnricher:
    global _APP_STORE_REVIEW_ENRICHER
    if _APP_STORE_REVIEW_ENRICHER is None:
        _APP_STORE_REVIEW_ENRICHER = ReviewEnricher()
    return _APP_STORE_REVIEW_ENRICHER


def _enrich_app_store_reviews(reviews: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    if not reviews:
        return reviews

    enricher = _get_app_store_enricher()
    enriched: List[Dict[str, Any]] = []

    for review in reviews:
        body = strip_redacted_text(review.get("body") or review.get("text") or "")
        title = strip_redacted_text(review.get("title") or "")
        rating = review.get("rating") or review.get("user_rating")

        if not body and not title:
            enriched.append(review)
            continue

        try:
            rating_value = float(rating) if rating is not None else None
        except (TypeError, ValueError):
            rating_value = None

        metadata = enricher.analyze_review(
            body=str(body),
            title=str(title) if title else None,
            rating=rating_value,
        )
        merged = review.copy()
        merged.update(metadata)
        enriched.append(merged)

    return enriched


async def _scrape_app_store_async(
    app_id: str,
    *,
    country: str,
    reviews: int,
    language: Optional[str] = None,
) -> Dict[str, Any]:
    scraper = SimpleAppStoreScraper()
    country_code = country.lower()

    details, reviews_payload = await asyncio.gather(
        scraper.fetch_app_details(app_id=str(app_id), country=country_code),
        scraper.fetch_reviews_rss(
            app_id=str(app_id),
            country=country_code,
            limit=reviews,
            language=language or "en",
        ),
    )

    if not details:
        raise RuntimeError(f"App Store uygulaması bulunamadı: {app_id}")

    reviews_list = reviews_payload.get("reviews", []) if reviews_payload else []

    return {
        "app_id": str(details.get("app_id") or app_id),
        "app_name": details.get("app_name") or "Unknown App",
        "app_url": details.get("app_store_url"),
        "country": country,
        "language": language or "en",
        "description": details.get("app_description"),
        "developer": details.get("developer"),
        "rating_value": details.get("user_rating"),
        "rating_count": details.get("user_rating_count"),
        "reviews_found": len(reviews_list),
        "reviews": _enrich_app_store_reviews(reviews_list),
        "store": "App Store",
    }


async def _scrape_play_store_async(
    app_id: str,
    *,
    country: str,
    reviews: int,
    language: Optional[str] = None,
    reviews_language: Optional[str] = None,
    reviews_sort: int = 2,
) -> Dict[str, Any]:
    scraper = PlayStoreScraper()
    return await scraper.scrape_app(
        app_id=app_id,
        country=country.lower(),
        language=language,
        reviews_limit=reviews,
        reviews_language=reviews_language,
        reviews_sort=reviews_sort,
        capture_reviews=True,
    )


def scrape_app_data(
    app_id: str,
    *,
    country: str,
    reviews: int,
    language: Optional[str] = None,
    reviews_language: Optional[str] = None,
    reviews_sort: str = "newest",
) -> Tuple[str, Dict[str, Any]]:
    """Scrape an app from the appropriate store and return (store_label, payload)."""
    sort_map = {
        "most_relevant": 1,
        "newest": 2,
        "rating": 3,
    }
    sort_code = sort_map.get(reviews_sort, 2)

    if is_play_store_app(app_id):
        result = asyncio.run(
            _scrape_play_store_async(
                app_id,
                country=country,
                reviews=reviews,
                language=language,
                reviews_language=reviews_language,
                reviews_sort=sort_code,
            )
        )
        result.setdefault("store", "Play Store")
        return "Play Store", result

    result = asyncio.run(
        _scrape_app_store_async(
            app_id,
            country=country,
            reviews=reviews,
            language=language,
        )
    )
    result.setdefault("store", "App Store")
    return "App Store", result
