#!/usr/bin/env python3
"""
Simple App Store Scraper for Unified Analyzer
Fetches app details and reviews without screenshots.
"""

import aiohttp
import asyncio
import hashlib
import math
from typing import Any, Dict, List, Optional, Set

from core.privacy import redact_text


def _redact_review_fields(review: Dict[str, Any]) -> Dict[str, Any]:
    """Mask PII in review fields before returning results."""
    sanitized = review.copy()
    sanitized_title = redact_text(str(review.get("title") or ""))
    sanitized_body = redact_text(str(review.get("body") or ""))
    sanitized["title"] = sanitized_title
    sanitized["body"] = sanitized_body
    return sanitized


class AppStoreScraper:
    """Simple App Store scraper for metadata and reviews."""
    
    async def fetch_app_details(
        self,
        app_id: str,
        country: str = "us",
    ) -> Optional[Dict[str, Any]]:
        """Fetch app details from iTunes Search API."""
        url = f"https://itunes.apple.com/lookup"
        params = {
            "id": app_id,
            "country": country,
            "entity": "software",
        }
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, params=params) as resp:
                    if resp.status != 200:
                        return None
                    
                    # Force JSON parsing regardless of content-type
                    data = await resp.json(content_type=None)
                    results = data.get("results", [])
                    
                    if not results:
                        return None
                    
                    app = results[0]
                    
                    return {
                        "app_id": app.get("trackId"),
                        "app_name": app.get("trackName"),
                        "app_store_url": app.get("trackViewUrl"),
                        "app_description": app.get("description"),
                        "developer": app.get("artistName"),
                        "user_rating": app.get("averageUserRating"),
                        "user_rating_count": app.get("userRatingCount"),
                        "price": app.get("formattedPrice"),
                        "category": app.get("primaryGenreName"),
                    }
        except Exception as e:
            print(f"Error fetching app details: {e}")
            return None
    
    async def fetch_reviews_rss(
        self,
        app_id: str,
        country: str = "us",
        limit: int = 100,
        language: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Fetch up to `limit` reviews via the paginated App Store RSS API."""
        normalized_country = (country or "us").upper()
        language = language or "en"
        language_param = language.split("-")[0].lower()

        base_url = (
            "https://itunes.apple.com/rss/customerreviews/"
            "page={page}/id={app_id}/sortby=mostrecent/json"
        )

        # RSS returns 50 reviews per page; grab a couple extra pages for safety.
        per_page_estimate = 50
        max_pages = max(1, min(10, math.ceil(limit / per_page_estimate) + 1))

        reviews: List[Dict[str, Any]] = []
        seen_ids: Set[str] = set()

        timeout = aiohttp.ClientTimeout(total=20)
        headers = {
            "Accept": "application/json",
            "User-Agent": "aso-cli/1.0 (+https://github.com/sercaneraslan/aso-yorum-cli)",
            "Accept-Language": language.replace("_", "-"),
        }

        async with aiohttp.ClientSession(timeout=timeout, headers=headers) as session:
            for page in range(1, max_pages + 1):
                if len(reviews) >= limit:
                    break

                url = base_url.format(page=page, app_id=app_id)
                params = {"cc": normalized_country, "l": language_param}

                try:
                    async with session.get(url, params=params) as resp:
                        if resp.status != 200:
                            break
                        payload = await resp.json(content_type=None)
                except Exception as exc:
                    print(f"Error fetching reviews page {page}: {exc}")
                    break

                entries = payload.get("feed", {}).get("entry", [])
                if not entries or len(entries) <= 1:
                    break

                # First entry contains app metadata; skip it.
                for entry in entries[1:]:
                    review_id = (entry.get("id") or {}).get("label") or ""
                    title = (entry.get("title") or {}).get("label") or ""
                    body = (entry.get("content") or {}).get("label") or ""
                    rating_str = (entry.get("im:rating") or {}).get("label")
                    author = (
                        ((entry.get("author") or {}).get("name") or {}).get("label") or ""
                    )
                    date = (
                        (entry.get("updated") or {}).get("label")
                        or (entry.get("im:releaseDate") or {}).get("label")
                        or ""
                    )
                    version = (entry.get("im:version") or {}).get("label") or None

                    try:
                        rating = float(rating_str) if rating_str is not None else 0.0
                    except (TypeError, ValueError):
                        rating = 0.0

                    signature_source = review_id or f"{author}:{date}:{title}:{body}"
                    signature = hashlib.sha256(signature_source.encode()).hexdigest()
                    if signature in seen_ids:
                        continue
                    seen_ids.add(signature)

                    user_hash = hashlib.sha256(author.encode()).hexdigest()[:16]
                    review_candidate = {
                        "title": title,
                        "body": body,
                        "rating": rating,
                        "user": f"anon_{user_hash}",
                        "date": date,
                        "version": version,
                    }
                    reviews.append(_redact_review_fields(review_candidate))

                    if len(reviews) >= limit:
                        break

        return {"reviews": reviews[:limit]}


async def main():
    """Test the scraper."""
    scraper = AppStoreScraper()
    
    # Test app details
    app_id = "1199564834"  # Adobe Scan
    print(f"Fetching app {app_id}...")
    
    details = await scraper.fetch_app_details(app_id, country="us")
    if details:
        print(f"✓ App: {details['app_name']}")
        print(f"  Rating: {details['user_rating']}")
        print(f"  Reviews: {details['user_rating_count']}")
    
    # Test reviews
    print(f"\nFetching reviews...")
    reviews_data = await scraper.fetch_reviews_rss(app_id, country="us", limit=10, language="en")
    reviews = reviews_data.get("reviews", [])
    print(f"✓ Fetched {len(reviews)} reviews")
    
    if reviews:
        print(f"\nFirst review:")
        print(f"  Title: {reviews[0]['title']}")
        print(f"  Rating: {reviews[0]['rating']}")
        print(f"  Body: {reviews[0]['body'][:100]}...")


if __name__ == "__main__":
    asyncio.run(main())
