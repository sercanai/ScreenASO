"""Google Play Store scraping utilities built on top of Crawl4AI.

This module provides a simplified PlayStoreScraper class that fetches:
- Basic app metadata (name, rating, rating count, description)
- User reviews using the PlayStoreReviewScraper

Screenshot downloading and other advanced features have been removed to keep
the implementation focused on ASO research needs.
"""

from __future__ import annotations

import asyncio
import json
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from bs4 import BeautifulSoup
from crawl4ai import AsyncWebCrawler

from .config import settings
from .play_store_reviews import PlayStoreReviewScraper, PlayStoreReview


PLAY_STORE_BASE_URL = "https://play.google.com/store/apps/details"
DEFAULT_COUNTRY = settings.default_country
DEFAULT_LANGUAGE = settings.default_language or "en"


@dataclass
class PlayStoreAppDetails:
    """Structured representation of key Play Store metadata."""

    app_id: str
    name: str
    url: str
    description: str
    developer: Optional[str]
    rating_value: Optional[float]
    rating_count: Optional[int]
    reviews: List[PlayStoreReview]


def _normalize_language(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    cleaned = value.strip().replace("-", "_")
    if not cleaned:
        return None
    parts = cleaned.split("_")
    if len(parts) == 1:
        return parts[0].lower()
    primary = parts[0].lower()
    secondary = parts[1].upper()
    return f"{primary}_{secondary}"


def _build_app_url(app_id: str, *, country: Optional[str], language: Optional[str]) -> str:
    params: List[str] = [f"id={app_id}"]
    if language:
        params.append(f"hl={language}")
    if country:
        params.append(f"gl={country.lower()}")
    return f"{PLAY_STORE_BASE_URL}?{'&'.join(params)}"


class PlayStoreScraper:
    """Async helper that fetches Google Play Store application data.
    
    Simplified version focused on metadata and reviews only.
    """

    def __init__(self) -> None:
        self._proxy = settings.http_proxy
        self._review_scraper = PlayStoreReviewScraper(proxy=self._proxy)

    async def _fetch_html(self, url: str) -> Optional[str]:
        """Fetch HTML content from the given URL."""
        async with AsyncWebCrawler() as crawler:
            result = await crawler.arun(
                url=url,
                wait_until="networkidle",
                bypass_cache=True,
                headers={"User-Agent": "Mozilla/5.0"},
            )
        if not result.success:
            print(f"✗ Failed to crawl {url}")
            return None
        return result.html

    def _parse_json_ld(self, html: str, app_id: str, url: str) -> Optional[PlayStoreAppDetails]:
        """Parse JSON-LD structured data from Play Store page."""
        soup = BeautifulSoup(html, "html.parser")
        scripts = soup.find_all("script", {"type": "application/ld+json"})
        
        for script in scripts:
            raw_text = script.string
            if raw_text is None:
                raw_text = "".join(part for part in script.contents if isinstance(part, str))
            if not raw_text:
                continue
            
            try:
                payload = json.loads(raw_text)
            except json.JSONDecodeError:
                continue

            candidates = payload if isinstance(payload, list) else [payload]
            for candidate in candidates:
                if not isinstance(candidate, dict):
                    continue
                if candidate.get("@type") not in {"SoftwareApplication", "MobileApplication"}:
                    continue

                # Extract rating information
                aggregate = candidate.get("aggregateRating") or {}
                rating_value: Optional[float] = None
                rating_count: Optional[int] = None
                
                try:
                    rating_value = float(aggregate.get("ratingValue")) if aggregate.get("ratingValue") else None
                except (TypeError, ValueError):
                    rating_value = None
                    
                try:
                    rating_count = int(aggregate.get("ratingCount")) if aggregate.get("ratingCount") else None
                except (TypeError, ValueError):
                    rating_count = None

                # Extract developer
                author = candidate.get("author") or candidate.get("publisher")
                developer = None
                if isinstance(author, dict):
                    developer = author.get("name")
                elif isinstance(author, str):
                    developer = author

                # Extract description (try JSON first, then HTML)
                description = candidate.get("description") or ""
                if isinstance(description, list):
                    description = "\n".join(str(item) for item in description)
                
                # If description is short, try to get full description from HTML
                if len(description) < 200 and html:
                    full_desc = self._extract_full_description(html)
                    if full_desc and len(full_desc) > len(description):
                        description = full_desc

                name = candidate.get("name") or app_id

                return PlayStoreAppDetails(
                    app_id=app_id,
                    name=name,
                    url=url,
                    description=description,
                    developer=developer,
                    rating_value=rating_value,
                    rating_count=rating_count,
                    reviews=[],
                )
        return None

    @staticmethod
    def _extract_full_description(html: str) -> Optional[str]:
        """Extract full app description from HTML."""
        try:
            soup = BeautifulSoup(html, "html.parser")
            
            # Try data-g-id selector (current Play Store layout)
            desc_elem = soup.select_one("[data-g-id='description']")
            if desc_elem:
                text = desc_elem.get_text(" ", strip=True)
                if len(text) > 100:
                    return text
            
            # Try div.bARER class
            desc_elem = soup.select_one("div.bARER")
            if desc_elem:
                text = desc_elem.get_text(" ", strip=True)
                if len(text) > 100:
                    return text
            
            # Try itemprop description
            desc_elem = soup.select_one("div[itemprop='description']")
            if desc_elem:
                text = desc_elem.get_text(" ", strip=True)
                if len(text) > 100:
                    return text
            
            return None
        except Exception:
            return None

    async def get_app_details(
        self,
        app_id: str,
        *,
        country: Optional[str] = None,
        language: Optional[str] = None,
    ) -> Optional[PlayStoreAppDetails]:
        normalized_language = _normalize_language(language) or _normalize_language(DEFAULT_LANGUAGE)
        normalized_country = (country or DEFAULT_COUNTRY or "us").lower()
        app_url = _build_app_url(app_id, country=normalized_country, language=normalized_language)
        html = await self._fetch_html(app_url)
        if not html:
            return None
        details = self._parse_json_ld(html, app_id, app_url)
        if details is None:
            print(f"✗ Failed to parse metadata for {app_id}")
        return details

    async def scrape_app(
        self,
        app_id: str,
        *,
        app_name: Optional[str] = None,
        country: str = DEFAULT_COUNTRY,
        language: Optional[str] = DEFAULT_LANGUAGE,
        group_name: Optional[str] = None,
        capture_reviews: bool = True,
        reviews_limit: int = 10,
        reviews_country: Optional[str] = None,
        reviews_language: Optional[str] = None,
        reviews_sort: int = 2,
    ) -> Dict[str, Any]:
        """Fetch metadata and reviews for a Google Play app.
        
        Args:
            app_id: Google Play app ID (e.g., 'com.spotify.music')
            app_name: Optional app name override
            country: Country code for metadata
            language: Language code for metadata
            group_name: Optional group name for organization
            capture_reviews: Whether to fetch reviews
            reviews_limit: Maximum number of reviews to fetch
            reviews_country: Country code for reviews (defaults to country)
            reviews_language: Language code for reviews (defaults to language)
            reviews_sort: Review sort order - 1 (most relevant), 2 (newest), 3 (rating)
            
        Returns:
            Dictionary with app metadata and reviews
        """

        details = await self.get_app_details(app_id, country=country, language=language)
        if not details:
            return {
                "app_id": app_id,
                "app_name": app_name or app_id,
                "app_url": _build_app_url(app_id, country=country, language=_normalize_language(language)),
                "country": country,
                "language": language,
                "group": group_name,
                "error": "Unable to fetch metadata",
            }

        resolved_name = app_name or details.name
        print(f"Scraping app: {resolved_name} (ID: {details.app_id})")
        print(f"URL: {details.url}")
        print(f"Country: {country}")
        if language:
            print(f"Language: {language}")
        if group_name:
            print(f"Group: {group_name}")

        # Fetch reviews if requested
        reviews: List[Dict[str, Any]] = []
        if capture_reviews:
            review_country = (reviews_country or country or DEFAULT_COUNTRY or "us")
            review_country = review_country.lower()
            review_language = reviews_language or language
            normalized_review_language = _normalize_language(review_language) if review_language else None
            print(
                f"\nFetching up to {reviews_limit} reviews for {resolved_name} "
                f"({review_country}/{normalized_review_language or '-'})..."
            )
            raw_reviews = await self._review_scraper.get_reviews(
                app_id=app_id,
                country=review_country,
                language=normalized_review_language,
                limit=reviews_limit,
                sort=reviews_sort,
            )
            for review in raw_reviews:
                payload = {
                    "username": review.username,
                    "rating": review.rating,
                    "title": review.title,
                    "body": review.body,
                    "date": review.date,
                    "helpful_count": review.helpful_count,
                    "version": review.version,
                }
                if review.analysis:
                    payload.update(review.analysis)
                reviews.append(payload)
            if reviews:
                print(f"  ✓ Fetched {len(reviews)} reviews")
            else:
                print("  ✗ No reviews retrieved")

        result: Dict[str, Any] = {
            "app_id": details.app_id,
            "app_name": resolved_name,
            "app_url": details.url,
            "country": country,
            "language": language,
            "description": details.description,
            "developer": details.developer,
            "rating_value": details.rating_value,
            "rating_count": details.rating_count,
            "reviews_found": len(reviews),
            "reviews": reviews,
            "group": group_name,
        }

        return result


async def main() -> None:
    """Example usage of the simplified PlayStoreScraper."""
    scraper = PlayStoreScraper()
    result = await scraper.scrape_app(
        app_id="com.spotify.music",
        country="us",
        language="en",
        group_name="spotify",
        capture_reviews=True,
        reviews_limit=10,
    )
    print("\n" + "=" * 60)
    print("Play Store Scraping Result:")
    print(json.dumps(result, indent=2, ensure_ascii=False))
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
