import asyncio
import hashlib
import json
import random
import uuid
import re
from argparse import ArgumentParser, Namespace
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import urlsplit, urlunsplit
import sys

from crawl4ai import AsyncWebCrawler, BrowserConfig, CacheMode, CrawlerRunConfig
from crawl4ai import JsonCssExtractionStrategy

from bs4 import BeautifulSoup

import aiohttp

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from .app_store_scraper import AppStoreScraper
from .config import settings
from .locale_utils import default_language_for_country, default_locale_for_country
from core.privacy import redact_text
from core.sentiment import ReviewEnricher


DEFAULT_DELAY_MIN = 2.0
DEFAULT_DELAY_MAX = 5.0

REVIEW_ENRICHER = ReviewEnricher()


@dataclass
class ScreenshotConfig:
    enabled: bool
    download: bool
    output_dir: Path
    device_type: str
    language: Optional[str]
    group_name: Optional[str]


@dataclass
class ReviewConfig:
    enabled: bool
    limit: int
    min_rating: float
    max_rating: Optional[float]
    language: Optional[str]
    page_delay: float
    max_pages: int
    country: str
    mode: str = "rss"


def slugify(text: str) -> str:
    cleaned = "".join(char.lower() if char.isalnum() else "_" for char in text)
    collapsed = "_".join(segment for segment in cleaned.split("_") if segment)
    return collapsed or "apps"


def normalize_language(value: Optional[str], default: str = "en-us") -> str:
    if not value:
        return default
    normalized = value.strip().replace("_", "-")
    parts = [segment for segment in normalized.split("-") if segment]
    if not parts:
        return default
    primary = parts[0].lower()
    if len(parts) == 1:
        if primary == "en":
            return "en-us"
        return primary
    secondary = parts[1].lower()
    return f"{primary}-{secondary}"


def format_reviews_markdown(apps: List[Dict[str, Any]]) -> str:
    lines: List[str] = []
    for app in apps:
        reviews = app.get("reviews") or []
        if not reviews:
            continue

        header_parts: List[str] = []
        app_name = app.get("app_name") or "Unknown App"
        header_parts.append(app_name)
        app_id = app.get("app_id")
        if app_id:
            header_parts.append(f"ID: {app_id}")
        lines.append(f"## {' — '.join(header_parts)}")
        lines.append("")

        for index, review in enumerate(reviews, start=1):
            title = review.get("title") or "Untitled"
            rating = review.get("rating")
            user = review.get("user") or "anon"
            date = review.get("date") or ""
            version = review.get("version")

            meta_parts: List[str] = []
            if rating is not None:
                if isinstance(rating, float):
                    rating_text = f"{rating:.1f}"
                else:
                    rating_text = str(rating)
                meta_parts.append(f"rating {rating_text}/5")
            if user:
                meta_parts.append(f"user {user}")
            if date:
                meta_parts.append(date)
            if version:
                meta_parts.append(f"version {version}")

            meta_suffix = f" ({', '.join(meta_parts)})" if meta_parts else ""
            lines.append(f"{index}. **{title}**{meta_suffix}")

            body = review.get("body", "").strip()
            if body:
                for paragraph in body.splitlines():
                    paragraph = paragraph.strip()
                    if paragraph:
                        lines.append(f"    {paragraph}")
                lines.append("")

        lines.append("")

    if not lines:
        return ""

    content = ["# App Store Reviews", ""]
    content.extend(line.rstrip() for line in lines)
    return "\n".join(content).rstrip() + "\n"


class AppStoreDetailScraper:
    """
    iTunes Search API ile alınan app ID'lerini Crawl4AI ile zenginleştirir.
    
    iTunes API'den: app_id, app_name, app_store_url
    Crawl4AI ile ekler: rating, description, screenshots, price, developer, etc.
    """
    
    def __init__(
        self,
        verbose: bool = False,
        screenshot_config: Optional[ScreenshotConfig] = None,
        review_config: Optional[ReviewConfig] = None,
    ):
        self.verbose = verbose
        self.screenshot_config = screenshot_config
        self.review_config = review_config
        self.screenshot_scraper: Optional[AppStoreScraper] = None
        if screenshot_config and screenshot_config.enabled:
            self.screenshot_scraper = AppStoreScraper(output_dir=str(screenshot_config.output_dir))
    
    async def fetch_app_details(
        self, 
        app_url: str, 
        app_name: str,
        delay: Optional[float] = None
    ) -> Dict[str, Any]:
        """
        Bir app'in detay sayfasından tüm bilgileri çek.
        
        Args:
            app_url: App Store detay sayfası URL'i
            app_name: App adı (log için)
            delay: Request arası bekleme süresi
            
        Returns:
            Dictionary with: rating, description, screenshots, price, etc.
        """
        if self.verbose:
            print(f"\n📱 {app_name}")
            print(f"   🔗 {app_url}")
        
        # Detaylı extraction schema
        detail_schema = {
            "name": "App Details",
            "baseSelector": "body",
            "fields": [
                # Rating
                {
                    "name": "rating_figure",
                    "selector": "figure.we-star-rating",
                    "type": "attribute",
                    "attribute": "aria-label",
                    "default": None,
                },
                # Description (uzun açıklama)
                {
                    "name": "description",
                    "selector": "div.section__description p",
                    "type": "text",
                    "default": "",
                },
                # Developer
                {
                    "name": "developer",
                    "selector": "h2.product-header__identity a",
                    "type": "text",
                    "default": "",
                },
                # Price
                {
                    "name": "price",
                    "selector": "li.inline-list__item--bulleted",
                    "type": "text",
                    "default": "Free",
                },
                # Category
                {
                    "name": "category",
                    "selector": "a.inline-list__item",
                    "type": "text",
                    "default": "",
                },
                # Age Rating
                {
                    "name": "age_rating",
                    "selector": "span.badge-age-rating",
                    "type": "text",
                    "default": "",
                },
                # Languages
                {
                    "name": "languages",
                    "selector": "div.information-list__item__definition dd",
                    "type": "text",
                    "default": "",
                },
            ],
        }
        
        browser_config = BrowserConfig(
            headless=True,
            verbose=False,
        )
        
        extraction_strategy = JsonCssExtractionStrategy(detail_schema, verbose=False)
        
        crawler_config = CrawlerRunConfig(
            cache_mode=CacheMode.BYPASS,
            extraction_strategy=extraction_strategy,
            wait_until="networkidle",
            page_timeout=20000,
        )
        
        result = {
            "success": False,
            "rating": None,
            "description": None,
            "developer": None,
            "price": None,
            "category": None,
            "age_rating": None,
            "screenshots": [],
        }
        
        try:
            async with AsyncWebCrawler(config=browser_config) as crawler:
                crawl_result = await crawler.arun(url=app_url, config=crawler_config)
                
                if not crawl_result.success or not crawl_result.extracted_content:
                    if self.verbose:
                        print(f"   ⚠️  Detaylar çekilemedi")
                    return result
                
                # JSON parse
                data = json.loads(crawl_result.extracted_content)
                
                if not data or len(data) == 0:
                    return result
                
                item = data[0]
                
                # Rating parse: "4.9 out of 5" -> 4.9
                rating_aria = item.get("rating_figure", "")
                if rating_aria and " out of " in rating_aria:
                    try:
                        rating_str = rating_aria.split(" out of ")[0].strip()
                        result["rating"] = float(rating_str)
                        if self.verbose:
                            print(f"   ⭐ Rating: {result['rating']}/5")
                    except ValueError:
                        pass
                
                # Description (full text)
                raw_desc = item.get("description")
                full_desc = self._extract_full_description(crawl_result.html)
                description_source = full_desc if full_desc is not None else (raw_desc or "")
                if isinstance(description_source, str):
                    description = description_source.strip()
                else:
                    description = ""
                if description:
                    result["description"] = description
                    if self.verbose:
                        print(f"   📝 Description: {len(description)} karakter")
                
                # Developer
                developer = item.get("developer", "").strip()
                if developer:
                    result["developer"] = developer
                    if self.verbose:
                        print(f"   👤 Developer: {developer}")
                
                # Price
                price = item.get("price", "").strip()
                if price and price != "Free":
                    result["price"] = price
                    if self.verbose:
                        print(f"   💰 Price: {price}")
                elif self.verbose:
                    print(f"   💰 Price: Free")
                
                # Category
                category = item.get("category", "").strip()
                if category:
                    result["category"] = category
                    if self.verbose:
                        print(f"   📂 Category: {category}")
                
                # Age Rating
                age_rating = item.get("age_rating", "").strip()
                if age_rating:
                    result["age_rating"] = age_rating
                
                result["success"] = True
                
        except Exception as exc:
            if self.verbose:
                print(f"   ✗ Hata: {exc}")
        
        return result
    
    def _extract_full_description(self, html: Optional[str]) -> Optional[str]:
        """Return the full app description extracted from the rendered HTML."""
        if not html:
            return None
        soup = BeautifulSoup(html, "html.parser")
        
        # Try to find main description paragraph (new App Store layout)
        # Look for paragraphs with substantial content (>100 chars)
        all_paragraphs = soup.find_all("p")
        for p in all_paragraphs:
            text = p.get_text(" ", strip=True)
            # Main description is usually the longest paragraph
            if len(text) > 200:
                return text
        
        # Fallback to old selectors
        selectors = [
            "section.section.section--product-details div.section__description",
            "section.section.section--product-details div.we-clamp__wrapper",
            "div.section__description",
            "div.we-clamp",
        ]
        for selector in selectors:
            container = soup.select_one(selector)
            if not container:
                continue
            paragraphs = [
                paragraph.get_text(" ", strip=True) for paragraph in container.find_all("p")
            ]
            paragraphs = [text for text in paragraphs if text]
            if paragraphs:
                return "\n\n".join(paragraphs)
            text = container.get_text(" ", strip=True)
            if text:
                return text
        
        # Last resort: meta description
        meta_description = soup.find("meta", attrs={"name": "description"})
        if meta_description and meta_description.get("content"):
            text = meta_description["content"].strip()
            if text:
                return text
        return None

    @staticmethod
    def _build_short_description(description: Optional[str], *, max_length: int = 200) -> Optional[str]:
        """Return a concise summary from the full description."""
        if not description:
            return None
        normalized = re.sub(r"\s+", " ", description).strip()
        if not normalized:
            return None

        sentences = re.split(r"(?<=[.!?])\s+", normalized)
        for sentence in sentences:
            trimmed = sentence.strip()
            if not trimmed:
                continue
            if len(trimmed) <= max_length:
                return trimmed
            break

        if len(normalized) <= max_length:
            return normalized

        truncated = normalized[:max_length].rstrip()
        if " " in truncated:
            truncated = truncated.rsplit(" ", 1)[0]
        return truncated + "..."
    
    @staticmethod
    def _parse_rating_label(label: Optional[str]) -> Optional[float]:
        if not label:
            return None
        match = re.search(r"([0-9]+(?:\.[0-9]+)?)", label)
        if not match:
            return None
        try:
            return float(match.group(1))
        except ValueError:
            return None

    @staticmethod
    def _anonymize_user(user: Optional[str]) -> str:
        if not user:
            return "anon"
        normalized = user.strip()
        if not normalized:
            return "anon"
        digest = hashlib.sha256(normalized.lower().encode("utf-8")).hexdigest()[:8]
        return f"anon_{digest}"

    @staticmethod
    def _redact_review_fields(
        reviews: List[Dict[str, Any]],
        *,
        language: Optional[str],
    ) -> List[Dict[str, Any]]:
        if not reviews or not language:
            return reviews

        sanitized: List[Dict[str, Any]] = []
        for review in reviews:
            redacted_title = redact_text(review.get("title", ""), language=language)
            redacted_body = redact_text(review.get("body", ""), language=language)
            enriched = {
                **review,
                "title": redacted_title,
                "body": redacted_body,
            }
            try:
                analysis = REVIEW_ENRICHER.analyze_review(
                    body=redacted_body,
                    title=redacted_title,
                    rating=review.get("rating"),
                    language_hint=language,
                )
            except Exception as exc:
                analysis = {"analysis_error": str(exc)}
            enriched.update(analysis)
            sanitized.append(enriched)
        return sanitized

    async def _fetch_reviews_html(
        self,
        *,
        app_id: Optional[Any],
        app_name: str,
        app_url: str,
        country: str,
    ) -> Dict[str, Any]:
        if not self.review_config or not self.review_config.enabled:
            return {}
        if not app_id:
            if self.verbose:
                print("   ✗ App ID yok, review adımı atlandı")
            return {"reviews_enriched": False}

        config = self.review_config

        target_country = config.country.lower()
        language = config.language or "en-us"

        # Base URL hazırlığı
        parts = urlsplit(app_url)
        path_segments = parts.path.split("/")
        if len(path_segments) > 1:
            path_segments[1] = target_country
        normalized_path = "/".join(path_segments)
        base_url = urlunsplit((parts.scheme, parts.netloc, normalized_path, "", ""))
        query_params = ["see-all=reviews"]

        if language:
            query_params.append(f"l={language}")

        def build_review_url(page_index: int) -> str:
            params = list(query_params)
            if page_index > 1:
                params.append(f"page={page_index}")
            query = "&".join(params)
            return f"{base_url}?{query}"

        headers = None
        if language:
            primary, _, secondary = language.partition("-")
            if secondary:
                header_language = f"{primary}-{secondary.upper()}"
            else:
                header_language = primary
            headers = {"Accept-Language": header_language}

        browser_config = BrowserConfig(headless=True, verbose=False)
        crawler_config = CrawlerRunConfig(
            cache_mode=CacheMode.BYPASS,
            wait_until="networkidle",
            page_timeout=20000,
        )

        reviews: List[Dict[str, Any]] = []
        fetched_pages = 0
        skipped_due_to_links = 0
        skipped_due_to_rating = 0
        total_seen = 0

        try:
            async with AsyncWebCrawler(config=browser_config) as crawler:
                page_index = 1
                while len(reviews) < config.limit and page_index <= config.max_pages:
                    page_url = build_review_url(page_index)
                    if self.verbose:
                        print(f"   🔄 Reviews sayfası {page_index}: {page_url}")

                    crawl_result = await crawler.arun(
                        url=page_url,
                        config=crawler_config,
                        headers=headers,
                    )

                    if not crawl_result.success or not crawl_result.html:
                        if self.verbose:
                            print("   ✗ Review sayfası yüklenemedi")
                        break

                    soup = BeautifulSoup(crawl_result.html, "html.parser")
                    review_nodes = soup.select("div.we-customer-review")
                    if not review_nodes:
                        break

                    fetched_pages += 1

                    for node in review_nodes:
                        total_seen += 1
                        rating_node = node.select_one("figure.we-star-rating")
                        rating = self._parse_rating_label(
                            rating_node.get("aria-label") if rating_node else None
                        )
                        if rating is None:
                            continue
                        if rating < config.min_rating:
                            skipped_due_to_rating += 1
                            continue
                        if config.max_rating is not None and rating > config.max_rating:
                            skipped_due_to_rating += 1
                            continue

                        body_el = node.select_one(".we-customer-review__body")
                        if body_el:
                            body_text = body_el.get_text(" ", strip=True)
                        else:
                            body_text = ""

                        if not body_text:
                            continue

                        if re.search(r"(https?://\S+|www\.\S+)", body_text, re.IGNORECASE):
                            skipped_due_to_links += 1
                            continue

                        body_text = re.sub(r"\s+", " ", body_text).strip()
                        if not body_text:
                            continue

                        title_el = node.select_one("h3.we-customer-review__title")
                        title = title_el.get_text(strip=True) if title_el else ""

                        user_el = node.select_one("span.we-customer-review__user")
                        raw_user = user_el.get_text(strip=True) if user_el else ""
                        user = self._anonymize_user(raw_user)

                        date_el = node.select_one("time")
                        review_date = (
                            date_el.get("datetime") or date_el.get_text(strip=True) if date_el else ""
                        )

                        version_el = node.select_one("span.we-customer-review__version")
                        app_version = (
                            version_el.get_text(strip=True).replace("Version ", "") if version_el else None
                        )

                        review = {
                            "title": title,
                            "rating": rating,
                            "user": user,
                            "date": review_date,
                            "version": app_version,
                            "body": body_text,
                        }
                        reviews.append(review)

                        if len(reviews) >= config.limit:
                            break

                    page_index += 1
                    if len(reviews) >= config.limit:
                        break
                    await asyncio.sleep(config.page_delay)

        except Exception as exc:
            if self.verbose:
                print(f"   ✗ Review hatası: {exc}")
            return {"reviews_enriched": False}

        if self.verbose and skipped_due_to_links:
            print(f"   ⚠️ Link içerdiği için atlanan review: {skipped_due_to_links}")
        if self.verbose and skipped_due_to_rating:
            print(f"   ⚠️ Rating filtresiyle atlanan review: {skipped_due_to_rating}")

        sanitized_reviews = self._redact_review_fields(reviews, language=language)

        return {
            "reviews": sanitized_reviews,
            "reviews_count": len(sanitized_reviews),
            "reviews_limit": config.limit,
            "reviews_seen": total_seen,
            "reviews_pages_fetched": fetched_pages,
            "reviews_skipped_links": skipped_due_to_links,
            "reviews_skipped_rating": skipped_due_to_rating,
            "reviews_country": target_country,
            "reviews_language": language,
            "reviews_enriched": bool(reviews),
        }

    async def _enrich_with_reviews(
        self,
        *,
        app_id: Optional[Any],
        app_name: str,
        app_url: str,
        country: str,
    ) -> Dict[str, Any]:
        if not self.review_config or not self.review_config.enabled:
            return {}
        if not app_id:
            if self.verbose:
                print("   ✗ App ID yok, review adımı atlandı")
            return {"reviews_enriched": False}

        mode = (self.review_config.mode or "rss").lower()

        if mode == "rss":
            rss_result = await self._fetch_reviews_rss(app_id=app_id)
            if rss_result.get("reviews"):
                return rss_result
            if self.verbose:
                print("   ⚠️ RSS sonuç vermedi, HTML moduna düşülüyor")
            # HTML fallback ile en azından ilk sayfadaki yorumları almayı dene
            return await self._fetch_reviews_html(
                app_id=app_id,
                app_name=app_name,
                app_url=app_url,
                country=country,
            )

        if mode == "html":
            return await self._fetch_reviews_html(
                app_id=app_id,
                app_name=app_name,
                app_url=app_url,
                country=country,
            )

        if self.verbose:
            print(f"   ⚠️ Review modu desteklenmiyor: {mode}")
        return {"reviews_enriched": False}

    async def _fetch_reviews_rss(self, *, app_id: Any) -> Dict[str, Any]:
        config = self.review_config
        target_country = (config.country or "us").upper()
        language = config.language or "en-us"
        language_param = language.split("-")[0] if language else "en"

        base_url = (
            "https://itunes.apple.com/rss/customerreviews/"
            "page={page}/id={app_id}/sortby=mostrecent/json"
        )

        reviews: List[Dict[str, Any]] = []
        fetched_pages = 0
        skipped_links = 0
        skipped_rating = 0
        total_seen = 0

        timeout = aiohttp.ClientTimeout(total=15)
        headers = {
            "Accept": "application/json",
            "User-Agent": "crawl4ai-review-fetcher/1.0",
        }
        headers["Accept-Language"] = language.replace("_", "-")

        async with aiohttp.ClientSession(timeout=timeout, headers=headers) as session:
            for page_index in range(1, config.max_pages + 1):
                if len(reviews) >= config.limit:
                    break

                url = base_url.format(page=page_index, app_id=app_id)
                params = {"l": language_param, "cc": target_country}

                try:
                    async with session.get(url, params=params) as response:
                        if response.status != 200:
                            if self.verbose:
                                print(f"   ✗ RSS HTTP {response.status}: {url}")
                            break
                        payload = await response.json(content_type=None)
                except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
                    if self.verbose:
                        print(f"   ✗ RSS isteği hata verdi: {exc}")
                    break
                except json.JSONDecodeError as exc:
                    if self.verbose:
                        print(f"   ✗ RSS JSON çözümlenemedi: {exc}")
                    break

                entries = payload.get("feed", {}).get("entry", [])
                if not entries or len(entries) <= 1:
                    if self.verbose:
                        print(f"   ⚠️ RSS sayfası {page_index} için review bulunamadı")
                    break

                fetched_pages += 1

                for entry in entries[1:]:
                    total_seen += 1

                    rating_str = entry.get("im:rating", {}).get("label")
                    try:
                        rating = float(rating_str)
                    except (TypeError, ValueError):
                        continue

                    if rating < config.min_rating:
                        skipped_rating += 1
                        continue
                    if config.max_rating is not None and rating > config.max_rating:
                        skipped_rating += 1
                        continue

                    body = (entry.get("content", {}) or {}).get("label", "").strip()
                    if not body:
                        continue

                    if re.search(r"(https?://\\S+|www\\.\\S+)", body, re.IGNORECASE):
                        skipped_links += 1
                        continue

                    title = entry.get("title", {}).get("label", "") or ""
                    raw_user = (entry.get("author", {}) or {}).get("name", {}).get("label", "") or ""
                    user = self._anonymize_user(raw_user)
                    review_date = (
                        entry.get("updated", {}).get("label")
                        or entry.get("im:releaseDate", {}).get("label")
                        or ""
                    )
                    app_version = (entry.get("im:version", {}) or {}).get("label")

                    reviews.append(
                        {
                            "title": title,
                            "rating": rating,
                            "user": user,
                            "date": review_date,
                            "version": app_version,
                            "body": body,
                        }
                    )

                    if len(reviews) >= config.limit:
                        break

                if len(reviews) >= config.limit:
                    break

                if page_index < config.max_pages:
                    await asyncio.sleep(config.page_delay)

        if self.verbose:
            print(
                f"   ✓ RSS review özet: sayfa={fetched_pages}, alınan={len(reviews)}, "
                f"rating filtresi={skipped_rating}, link filtresi={skipped_links}"
            )

        sanitized_reviews = self._redact_review_fields(reviews, language=language)

        return {
            "reviews": sanitized_reviews,
            "reviews_count": len(sanitized_reviews),
            "reviews_limit": config.limit,
            "reviews_seen": total_seen,
            "reviews_pages_fetched": fetched_pages,
            "reviews_skipped_links": skipped_links,
            "reviews_skipped_rating": skipped_rating,
            "reviews_country": target_country,
            "reviews_language": language,
            "reviews_enriched": bool(reviews),
        }

    async def _enrich_with_screenshots(
        self,
        *,
        app_id: Optional[Any],
        app_name: str,
        country: str,
    ) -> Dict[str, Any]:
        if not self.screenshot_scraper or not self.screenshot_config:
            return {}
        if not app_id:
            if self.verbose:
                print("   ✗ App ID yok, screenshot adımı atlandı")
            return {"screenshots_enriched": False}

        try:
            screenshot_result = await self.screenshot_scraper.scrape_app(
                app_id=str(app_id),
                app_name=app_name,
                country=country,
                download=self.screenshot_config.download,
                device_type=self.screenshot_config.device_type,
                language=self.screenshot_config.language,
                group_name=self.screenshot_config.group_name,
            )
        except Exception as exc:
            if self.verbose:
                print(f"   ✗ Screenshot hatası: {exc}")
            return {"screenshots_enriched": False}

        images = screenshot_result.get("images", [])
        images_found = screenshot_result.get("images_found", len(images))
        downloaded_count = screenshot_result.get("downloaded_count", 0)

        directory = None
        if images:
            try:
                directory = str(Path(images[0]["path"]).parent)
            except Exception:
                directory = None

        updates: Dict[str, Any] = {
            "screenshots": images,
            "screenshots_found": images_found,
            "screenshots_downloaded": downloaded_count,
            "screenshots_dir": directory,
            "screenshots_enriched": bool(images),
        }

        if self.verbose:
            if images:
                print(f"   ✓ Screenshots: {images_found} adet")
                if self.screenshot_config.download:
                    print(f"   ✓ İndirilen: {downloaded_count}")
            else:
                print("   ✗ Screenshot bulunamadı")

        return updates
    
    async def enrich_apps(
        self,
        apps: List[Dict[str, Any]],
        delay: Optional[float] = None,
        max_apps: Optional[int] = None,
        country: str = "us",
    ) -> List[Dict[str, Any]]:
        """
        iTunes API'den gelen app listesini Crawl4AI ile zenginleştir.
        
        Args:
            apps: iTunes API'den gelen app listesi
            delay: Request arası bekleme süresi (saniye)
            max_apps: Maksimum işlenecek app sayısı
            
        Returns:
            Zenginleştirilmiş app listesi
        """
        # Delay hesapla
        if delay is not None:
            delay_min = delay
            delay_max = delay * 1.5
        else:
            delay_min = DEFAULT_DELAY_MIN
            delay_max = DEFAULT_DELAY_MAX
        
        # Limit uygula
        if max_apps:
            apps = apps[:max_apps]
        
        print(f"\n📊 {len(apps)} uygulama zenginleştirilecek...")
        if self.verbose:
            print(f"⏳ Her request arası {delay_min:.1f}-{delay_max:.1f} saniye bekleme")
            print(f"⏱️  Tahmini süre: ~{len(apps) * ((delay_min + delay_max) / 2 + 3):.0f} saniye\n")
        
        enriched = []
        
        for idx, app in enumerate(apps, 1):
            app_id = app.get("app_id")
            app_url = app.get("app_store_url")
            app_name = app.get("app_name", "Unknown")
            
            if not app_url:
                if self.verbose:
                    print(f"[{idx}/{len(apps)}] {app_name} - URL yok, atlanıyor")
                enriched.append(app)
                continue
            
            if self.verbose:
                print(f"[{idx}/{len(apps)}]", end=" ")
            
            # Detayları çek
            details = await self.fetch_app_details(app_url, app_name, delay)
            
            # Mevcut bilgilerle birleştir
            enriched_app = {**app}  # Original data
            full_description = details.get("description")
            enrichment_updates = {
                "app_description": full_description,
                "developer": details.get("developer"),
                "price": details.get("price") or "Free",
                "category": details.get("category"),
                "age_rating": details.get("age_rating"),
                "enriched": details.get("success", False),
            }
            short_description = self._build_short_description(full_description)
            if short_description:
                enrichment_updates["app_description_short"] = short_description
            rating = details.get("rating")
            if rating is not None:
                enrichment_updates["user_rating"] = rating

            if self.review_config and self.review_config.enabled:
                review_updates = await self._enrich_with_reviews(
                    app_id=app_id,
                    app_name=app_name,
                    app_url=app_url,
                    country=app.get("country", country),
                )
                enrichment_updates.update(review_updates)
            if "reviews" not in enrichment_updates:
                enrichment_updates["reviews"] = []
                if "reviews_count" not in enrichment_updates:
                    enrichment_updates["reviews_count"] = 0
            
            if self.screenshot_config and self.screenshot_config.enabled:
                screenshot_updates = await self._enrich_with_screenshots(
                    app_id=app_id,
                    app_name=app_name,
                    country=app.get("country", country),
                )
                enrichment_updates.update(screenshot_updates)

            enriched_app.update(enrichment_updates)
            
            enriched.append(enriched_app)
            
            # Rate limiting
            if idx < len(apps):
                wait_time = random.uniform(delay_min, delay_max)
                if self.verbose:
                    print(f"   ⏳ {wait_time:.1f}s bekleniyor...")
                await asyncio.sleep(wait_time)
        
        print(f"\n✓ Zenginleştirme tamamlandı!")
        successful = sum(1 for app in enriched if app.get("enriched", False))
        print(f"  Başarılı: {successful}/{len(enriched)}")
        if self.review_config and self.review_config.enabled:
            reviews_success = sum(1 for app in enriched if app.get("reviews_enriched"))
            total_reviews = sum(app.get("reviews_count", 0) for app in enriched)
            print(f"  ✓ Reviews: {reviews_success}/{len(enriched)} (toplam {total_reviews})")
        if self.screenshot_config and self.screenshot_config.enabled:
            screenshot_success = sum(1 for app in enriched if app.get("screenshots_enriched"))
            print(f"  ✓ Screenshots: {screenshot_success}/{len(enriched)}")
            if self.screenshot_config.download:
                downloaded_total = sum(app.get("screenshots_downloaded", 0) for app in enriched)
                print(f"  ✓ İndirilen görüntü sayısı: {downloaded_total}")

        return enriched


async def run_enrichment(args: Namespace) -> None:
    """CLI üzerinden zenginleştirme çalıştır."""
    
    # Input JSON'u oku
    input_path = Path(args.input)
    if not input_path.exists():
        print(f"✗ Dosya bulunamadı: {input_path}")
        return
    
    print(f"📂 Input: {input_path}")
    run_started = datetime.now(timezone.utc)
    run_uuid = str(uuid.uuid4())
    if args.verbose:
        print(f"🆔 Run UUID: {run_uuid}")
    
    with open(input_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    
    query_info = data.get("query", {})
    country = (query_info.get("country") or settings.default_country).lower()
    keyword = query_info.get("keyword")
    source_device = query_info.get("device")
    raw_source_lang = query_info.get("lang")
    if raw_source_lang:
        source_lang = normalize_language(raw_source_lang)
    else:
        default_lang = default_language_for_country(country, settings.default_language)
        source_lang = normalize_language(f"{default_lang}-{country}")

    # Apps listesini al
    apps = data.get("apps", [])
    if not apps:
        print("✗ 'apps' listesi bulunamadı veya boş")
        return
    
    print(f"✓ {len(apps)} uygulama bulundu")

    capture_screenshots = args.capture_screenshots or args.download_screenshots
    screenshot_config: Optional[ScreenshotConfig] = None
    if capture_screenshots:
        target_dir = (
            Path(args.screenshots_dir).expanduser()
            if args.screenshots_dir
            else settings.screenshot_output_dir
        )
        target_dir.mkdir(parents=True, exist_ok=True)

        device_from_args = args.screenshots_device.lower() if args.screenshots_device else None
        device_fallback = source_device or settings.default_device
        device_type = (device_from_args or device_fallback).lower()
        allowed_devices = {"iphone", "ipad", "appletv", "all"}
        if device_type not in allowed_devices:
            print(f"✗ Geçersiz cihaz parametresi: {device_type}")
            return

        default_group = f"{keyword}_{country}" if keyword else country
        group_raw = args.screenshots_group or default_group
        group_name = slugify(group_raw) if group_raw else None

        language = normalize_language(
            args.screenshots_language
            or source_lang
            or f"{default_language_for_country(country, settings.default_language)}-{country}"
        )

        screenshot_config = ScreenshotConfig(
            enabled=True,
            download=args.download_screenshots,
            output_dir=target_dir,
            device_type=device_type,
            language=language,
            group_name=group_name,
        )

        if args.download_screenshots:
            print(f"📸 Screenshot indirme aktif (klasör: {target_dir})")
        else:
            print("📸 Screenshot meta verileri toplanacak (indirilmeyecek)")

    review_config: Optional[ReviewConfig] = None
    if args.capture_reviews:
        reviews_limit = max(1, min(args.reviews_limit, 100))
        min_rating = max(0.0, min(5.0, args.reviews_min_rating))
        max_rating = args.reviews_max_rating
        if max_rating is not None:
            max_rating = max(0.0, min(5.0, max_rating))
            if max_rating < min_rating:
                print("✗ reviews-max-rating, min rating'den küçük. Ayar yoksayılıyor.")
                max_rating = None

        default_reviews_country = settings.default_country.lower()
        country_override = (args.reviews_country or country or default_reviews_country).lower()
        if len(country_override) != 2 or not country_override.isalpha():
            print(
                f"✗ Geçersiz reviews-country değeri: {country_override}, "
                f"'{default_reviews_country}' kullanılacak."
            )
            country_override = default_reviews_country

        default_review_language = normalize_language(
            args.reviews_language
            or source_lang
            or f"{default_language_for_country(country_override, settings.default_language)}-{country_override}"
        )
        review_language = default_review_language
        page_delay = max(0.5, args.reviews_page_delay)
        max_pages = max(1, min(args.reviews_max_pages, 10))

        review_config = ReviewConfig(
            enabled=True,
            limit=reviews_limit,
            min_rating=min_rating,
            max_rating=max_rating,
            language=review_language,
            page_delay=page_delay,
            max_pages=max_pages,
            country=country_override,
            mode=args.reviews_mode,
        )

        rating_desc = f"{min_rating}+" if max_rating is None else f"{min_rating}-{max_rating}"
        print(
            f"📝 Review toplama aktif (mod {args.reviews_mode}, ülke {country_override.upper()}, "
            f"limit {reviews_limit}, rating filtre {rating_desc})"
        )
        print(f"   Dil: {review_language}, link içeren review'lar güvenlik için atlanacak.")
    
    # Zenginleştir
    scraper = AppStoreDetailScraper(
        verbose=args.verbose,
        screenshot_config=screenshot_config,
        review_config=review_config,
    )
    enriched_apps = await scraper.enrich_apps(
        apps,
        delay=args.delay,
        max_apps=args.limit if args.limit else None,
        country=country,
    )

    output_path = (
        Path(args.output)
        if args.output
        else input_path.parent / f"{input_path.stem}_enriched.json"
    )

    reviews_markdown_path: Optional[Path] = None
    if review_config:
        markdown_content = format_reviews_markdown(enriched_apps)
        if markdown_content:
            reviews_markdown_path = output_path.with_suffix(".reviews.md")
            with reviews_markdown_path.open("w", encoding="utf-8") as handle:
                handle.write(markdown_content)
            print(f"✓ Reviews markdown kaydedildi: {reviews_markdown_path}")
    
    # Output JSON'u oluştur
    finished_at = datetime.now(timezone.utc)
    output_data = {**data}
    output_data["apps"] = enriched_apps
    output_data["enriched_at"] = finished_at.isoformat()
    output_data["enriched_count"] = sum(1 for app in enriched_apps if app.get("enriched", False))
    if review_config:
        output_data["review_summary"] = {
            "enabled": True,
            "limit": review_config.limit,
            "min_rating": review_config.min_rating,
            "max_rating": review_config.max_rating,
            "language": review_config.language,
            "country": review_config.country,
            "mode": review_config.mode,
            "apps_with_reviews": sum(
                1 for app in enriched_apps if app.get("reviews_enriched")
            ),
            "reviews_total": sum(app.get("reviews_count", 0) for app in enriched_apps),
            "skipped_links": sum(app.get("reviews_skipped_links", 0) for app in enriched_apps),
            "skipped_rating": sum(app.get("reviews_skipped_rating", 0) for app in enriched_apps),
            "pages_fetched": sum(app.get("reviews_pages_fetched", 0) for app in enriched_apps),
        }
        if reviews_markdown_path:
            output_data["review_summary"]["markdown_path"] = str(reviews_markdown_path)
    if reviews_markdown_path:
        output_data["reviews_markdown_path"] = str(reviews_markdown_path)
    if screenshot_config:
        output_data["screenshot_summary"] = {
            "enabled": True,
            "download": screenshot_config.download,
            "device_type": screenshot_config.device_type,
            "language": screenshot_config.language,
            "group_name": screenshot_config.group_name,
            "output_dir": str(screenshot_config.output_dir),
            "apps_with_screenshots": sum(
                1 for app in enriched_apps if app.get("screenshots_enriched")
            ),
            "downloaded_images": sum(app.get("screenshots_downloaded", 0) for app in enriched_apps),
        }
    output_data["run_uuid"] = run_uuid
    output_data["started_at"] = run_started.isoformat()
    output_data["finished_at"] = finished_at.isoformat()

    # Kaydet
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(output_data, f, indent=2, ensure_ascii=False)
        f.write("\n")

    print(f"\n✓ Sonuç kaydedildi: {output_path}")

    if args.persist:
        persist_db_path = (
            Path(args.persist_db).expanduser()
            if args.persist_db
            else settings.database_path
        )
        try:
            from ingest_to_sqlite import ingest_paths

            await ingest_paths(
                [output_path],
                persist_db_path,
                run_uuid=run_uuid,
                verbose=args.verbose,
            )
            print(f"✓ SQLite persist tamamlandı: {persist_db_path}")
        except Exception as exc:
            print(f"✗ SQLite persist hatası: {exc}")


def parse_args() -> Namespace:
    """Komut satırı argümanları."""
    parser = ArgumentParser(
        description="iTunes Search API sonuçlarını Crawl4AI ile zenginleştir."
    )
    parser.add_argument(
        "--input",
        "-i",
        required=True,
        help="iTunes Search API JSON dosyası (app_store_search.py çıktısı)",
    )
    parser.add_argument(
        "--output",
        "-o",
        default=None,
        help="Çıktı dosyası. Varsayılan: <input>_enriched.json",
    )
    parser.add_argument(
        "--limit",
        "-l",
        type=int,
        default=None,
        help="Maksimum işlenecek app sayısı (test için)",
    )
    parser.add_argument(
        "--delay",
        "-d",
        type=float,
        default=None,
        help=f"Request arası bekleme (saniye). Varsayılan: {DEFAULT_DELAY_MIN}-{DEFAULT_DELAY_MAX}",
    )
    parser.add_argument(
        "--capture-screenshots",
        action="store_true",
        help="[OPSIYONEL] App Store screenshot meta verilerini topla (indirimsiz).",
    )
    parser.add_argument(
        "--download-screenshots",
        action="store_true",
        help="[OPSIYONEL] Screenshot dosyalarını indir (meta veriler de toplanır).",
    )
    parser.add_argument(
        "--screenshots-dir",
        default=str(settings.screenshot_output_dir),
        help=f"Screenshot çıktı klasörü (varsayılan: {settings.screenshot_output_dir}).",
    )
    parser.add_argument(
        "--screenshots-device",
        default=None,
        help="Screenshot platformu (iphone, ipad, appletv, all). Varsayılan: arama cihazı.",
    )
    parser.add_argument(
        "--screenshots-language",
        default=None,
        help="Screenshot isteği için dil parametresi (örn. tr-tr). Varsayılan: arama dili.",
    )
    parser.add_argument(
        "--screenshots-group",
        default=None,
        help="Screenshot klasör grubu (varsayılan: arama keyword'ü slug).",
    )
    parser.add_argument(
        "--capture-reviews",
        action="store_true",
        help="App Store kullanıcı yorumlarını JSON çıktısına ekle.",
    )
    parser.add_argument(
        "--reviews-limit",
        type=int,
        default=100,
        help="Toplanacak maksimum yorum sayısı (varsayılan: 100, tavsiye edilen).",
    )
    parser.add_argument(
        "--reviews-min-rating",
        type=float,
        default=0.0,
        help="Filtreleme için minimum rating değeri (0-5 arası).",
    )
    parser.add_argument(
        "--reviews-max-rating",
        type=float,
        default=None,
        help="Opsiyonel maksimum rating filtresi (örn. sadece 5 yıldız).",
    )
    parser.add_argument(
        "--reviews-language",
        default=None,
        help="Yorum sayfası için dil parametresi (örn. tr-tr). Varsayılan: arama dili.",
    )
    parser.add_argument(
        "--reviews-country",
        default=None,
        help=(
            "Yorumların çekileceği ülke kodu "
            f"(varsayılan: input dosyası veya {settings.default_country})."
        ),
    )
    parser.add_argument(
        "--reviews-mode",
        choices=["rss", "html"],
        default="rss",
        help="Yorum toplama yöntemi (varsayılan: rss).",
    )
    parser.add_argument(
        "--reviews-page-delay",
        type=float,
        default=2.0,
        help="Review sayfaları arasında beklenecek süre (saniye). Varsayılan: 2.0.",
    )
    parser.add_argument(
        "--reviews-max-pages",
        type=int,
        default=10,
        help="Yorum sayfası sayısı üst limiti (varsayılan: 10).",
    )
    parser.add_argument(
        "--persist",
        action="store_true",
        help="[OPSIYONEL] Zenginleştirilmiş JSON'u SQLite veritabanına kaydet.",
    )
    parser.add_argument(
        "--persist-db",
        type=str,
        default=None,
        help="[OPSIYONEL] Persist işlemi için SQLite veritabanı yolu (varsayılan: data/screen_aso.db).",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Detaylı çıktı",
    )
    return parser.parse_args()


async def main() -> None:
    """Ana fonksiyon."""
    args = parse_args()
    await run_enrichment(args)


if __name__ == "__main__":
    asyncio.run(main())
