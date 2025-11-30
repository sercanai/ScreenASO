"""Google Play Store review extraction using Crawl4AI."""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
import textwrap
import urllib.parse
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import sys

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

import aiohttp
from bs4 import BeautifulSoup
from bs4.element import Tag
from crawl4ai import (
    AsyncWebCrawler,
    BrowserConfig,
    CacheMode,
    CrawlerRunConfig,
    VirtualScrollConfig,
)

from .config import settings
from core.privacy import redact_text, strip_redacted_text
from core.sentiment import ReviewEnricher


BATCHEXECUTE_URL = "https://play.google.com/_/PlayStoreUi/data/batchexecute"
MAX_REVIEWS_PER_REQUEST = 200

# Review sort options
SORT_MOST_RELEVANT = 1  # En alakalı (Most Relevant)
SORT_NEWEST = 2  # En yeni (Newest)
SORT_RATING = 3  # Puana göre (Rating)

DEFAULT_REVIEW_SORT = SORT_NEWEST  # Varsayılan: En yeni yorumlar
DEFAULT_TIMEOUT = aiohttp.ClientTimeout(total=20)
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/129.0.0.0 Safari/537.36"
)

REVIEW_ENRICHER = ReviewEnricher()


@dataclass
class PlayStoreReview:
    """Structured representation of a Play Store review with anonymized username."""

    username: str
    rating: Optional[float]
    title: str
    body: str
    date: str
    helpful_count: Optional[int]
    version: Optional[str]
    analysis: Dict[str, object] = field(default_factory=dict)


class PlayStoreReviewScraper:
    """Async helper that extracts reviews from Google Play Store."""

    def __init__(self, *, proxy: Optional[str] = None) -> None:
        self._proxy = proxy if proxy is not None else settings.http_proxy
        self._timeout = DEFAULT_TIMEOUT

    @staticmethod
    def _anonymize_user(user: Optional[str]) -> str:
        if not user:
            return "anon"
        normalized = user.strip()
        if not normalized:
            return "anon"
        digest = hashlib.sha256(normalized.lower().encode("utf-8")).hexdigest()[:8]
        return f"anon_{digest}"

    def _build_batchexecute_body(
        self,
        app_id: str,
        *,
        sort: int,
        count: int,
        token: Optional[str],
    ) -> str:
        safe_count = max(1, min(MAX_REVIEWS_PER_REQUEST, count))
        if token:
            page_fragment = f'[{safe_count},null,"{token}"]'
        else:
            page_fragment = f"[{safe_count},null,null]"
        # Correct format: the inner array structure must match Google's expected format
        inner = f'[null,null,[2,{sort},{page_fragment},null,[]],["{app_id}",7]]'
        # Escape the inner JSON properly
        inner_escaped = inner.replace('"', '\\"')
        f_req = f'[[["UsvDTd","{inner_escaped}",null,"generic"]]]'
        return "f.req=" + urllib.parse.quote(f_req, safe="")

    def _format_timestamp(self, raw: Any) -> str:
        if not isinstance(raw, list) or not raw:
            return ""
        seconds_raw = raw[0]
        nanos_raw = raw[1] if len(raw) > 1 else 0
        try:
            seconds = int(seconds_raw)
        except (TypeError, ValueError):
            return ""
        try:
            nanos = int(nanos_raw or 0)
        except (TypeError, ValueError):
            nanos = 0
        try:
            dt = datetime.fromtimestamp(seconds + nanos / 1_000_000_000, tz=timezone.utc)
            return dt.isoformat()
        except (OverflowError, OSError, ValueError):
            return str(seconds)

    def _build_review_from_entry(self, entry: Any) -> Optional[PlayStoreReview]:
        if not isinstance(entry, list) or len(entry) < 5:
            return None

        raw_user = None
        user_block = entry[1] if len(entry) > 1 else None
        if isinstance(user_block, list) and user_block:
            raw_user = user_block[0]

        username = self._anonymize_user(raw_user if isinstance(raw_user, str) else None)

        rating_value = entry[2] if len(entry) > 2 else None
        rating: Optional[float] = None
        if isinstance(rating_value, (int, float)):
            rating = float(rating_value)

        raw_title = entry[3] if len(entry) > 3 else None
        raw_body = entry[4] if len(entry) > 4 else ""

        cleaned_body = self._clean_review_text(raw_body or "")
        cleaned_title = self._clean_review_text(raw_title or "") if raw_title else ""

        title = cleaned_title
        body = cleaned_body
        if not title:
            derived_title, derived_body = self._split_title_and_body(cleaned_body)
            if derived_title:
                title = derived_title
            if derived_body:
                body = derived_body
        if not body:
            body = cleaned_body

        timestamp = entry[5] if len(entry) > 5 else None
        date_text = self._format_timestamp(timestamp)

        helpful_value = entry[6] if len(entry) > 6 else None
        helpful_count: Optional[int] = None
        if isinstance(helpful_value, (int, float)):
            helpful_count = int(helpful_value)

        version_raw = entry[10] if len(entry) > 10 else None
        version: Optional[str] = None
        if isinstance(version_raw, str) and version_raw.strip():
            version = version_raw.strip()
        elif isinstance(version_raw, (int, float)):
            version = str(version_raw)

        if not body and not title:
            return None

        return PlayStoreReview(
            username=username,
            rating=rating,
            title=title or "",
            body=body or "",
            date=date_text,
            helpful_count=helpful_count,
            version=version,
        )

    def _parse_batchexecute_payload(
        self,
        raw_text: str,
    ) -> Tuple[List[PlayStoreReview], Optional[str]]:
        if not raw_text:
            return [], None

        # Remove the XSSI protection prefix
        sanitized = raw_text.strip()
        if sanitized.startswith(")]}'"):
            sanitized = sanitized[4:]
        elif sanitized.startswith(")]}'\n"):
            sanitized = sanitized[5:]

        # Split by newlines and parse each line
        lines = [line.strip() for line in sanitized.split('\n') if line.strip()]
        
        payload_str: Optional[str] = None
        
        # Find the line with the actual data (skip the first line which is just a number)
        for line in lines[1:]:  # Skip first line (length indicator)
            try:
                outer = json.loads(line)
                if isinstance(outer, list) and outer:
                    # Look for wrb.fr wrapper
                    for chunk in outer:
                        if (
                            isinstance(chunk, list)
                            and len(chunk) >= 3
                            and chunk[0] == "wrb.fr"
                            and chunk[1] == "UsvDTd"
                            and isinstance(chunk[2], str)
                        ):
                            payload_str = chunk[2]
                            break
                    if payload_str:
                        break
            except json.JSONDecodeError:
                continue

        if payload_str is None:
            return [], None

        # Parse the actual payload
        try:
            payload = json.loads(payload_str)
        except json.JSONDecodeError:
            return [], None

        # Extract reviews and pagination token
        reviews_block = payload[0] if isinstance(payload, list) and payload else []
        next_token: Optional[str] = None
        if (
            isinstance(payload, list)
            and len(payload) > 1
            and isinstance(payload[1], list)
            and len(payload[1]) > 1
        ):
            token_candidate = payload[1][1]
            if isinstance(token_candidate, str) and token_candidate:
                next_token = token_candidate

        reviews: List[PlayStoreReview] = []
        if isinstance(reviews_block, list):
            for entry in reviews_block:
                review = self._build_review_from_entry(entry)
                if review:
                    reviews.append(review)

        return reviews, next_token

    async def _fetch_reviews_batchexecute(
        self,
        app_id: str,
        *,
        country: Optional[str],
        language: Optional[str],
        limit: int,
        sort: int = DEFAULT_REVIEW_SORT,
    ) -> List[PlayStoreReview]:
        params = {
            "rpcids": "UsvDTd",
            "source-path": f"/store/apps/details",
            "f.sid": "-1",
            "bl": "boq_playuiserver_20231101.08_p0",
            "hl": language or "en",
            "gl": (country or "us").lower(),
            "_reqid": "1234567",
            "rt": "c",
        }

        headers = {
            "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8",
            "User-Agent": DEFAULT_USER_AGENT,
            "X-Same-Domain": "1",
        }

        reviews: List[PlayStoreReview] = []
        token: Optional[str] = None
        seen_tokens: set[str] = set()
        request_count = 0
        max_requests = 50  # Safety limit

        async with aiohttp.ClientSession(timeout=self._timeout) as session:
            while len(reviews) < limit and request_count < max_requests:
                request_count += 1
                remaining = limit - len(reviews)
                batch_size = min(MAX_REVIEWS_PER_REQUEST, max(1, remaining))
                
                body = self._build_batchexecute_body(
                    app_id,
                    sort=sort,
                    count=batch_size,
                    token=token,
                )

                request_kwargs: dict[str, Any] = {}
                if self._proxy:
                    request_kwargs["proxy"] = self._proxy

                try:
                    async with session.post(
                        BATCHEXECUTE_URL,
                        params=params,
                        data=body,
                        headers=headers,
                        **request_kwargs,
                    ) as response:
                        if response.status != 200:
                            print(f"  ✗ HTTP {response.status} yanıtı (batchexecute)")
                            break
                        text = await response.text()

                    batch_reviews, next_token = self._parse_batchexecute_payload(text)
                    
                    if not batch_reviews:
                        print(f"  ⚠ İstek #{request_count}: Yorum bulunamadı")
                        break

                    added_count = 0
                    for review in batch_reviews:
                        if len(reviews) >= limit:
                            break
                        reviews.append(review)
                        added_count += 1

                    print(f"  ✓ İstek #{request_count}: {added_count} yorum eklendi (toplam: {len(reviews)})")

                    if not next_token or next_token in seen_tokens:
                        print(f"  ⚠ Pagination token bitti veya tekrar etti")
                        break

                    seen_tokens.add(next_token)
                    token = next_token
                    
                    # Small delay to avoid rate limiting
                    await asyncio.sleep(0.5)
                    
                except Exception as exc:  # noqa: BLE001
                    print(f"  ✗ İstek #{request_count} hatası: {exc}")
                    break

        return reviews

    async def _load_show_all_reviews_markup(
        self,
        url: str,
        *,
        app_id: str,
        limit: int,
    ) -> Optional[str]:
        """Open showAllReviews view and perform virtual scrolling."""

        separator = "&" if "?" in url else "?"
        target_url = f"{url}{separator}showAllReviews=true"
        session_id = f"play-showall-{app_id}-{uuid.uuid4().hex[:6]}"

        scroll_count = max(10, min(120, limit // 4 + 8))
        virtual_scroll = VirtualScrollConfig(
            container_selector="body",
            scroll_count=scroll_count,
            scroll_by="viewport",
            wait_after_scroll=1.2,
        )

        expand_js = """
        (() => {
            const buttons = Array.from(document.querySelectorAll('button, div[role="button"], span[role="button"]'));
            const terms = ['full review', 'read more', 'tam yorumu', 'daha fazla', 'mehr', 'más', 'leggi'];
            let expanded = 0;
            for (const btn of buttons) {
                const label = ((btn.textContent || '') + ' ' + (btn.getAttribute('aria-label') || '')).toLowerCase();
                if (terms.some(term => label.includes(term))) {
                    try { btn.click(); expanded += 1; } catch (e) {}
                }
            }
            return expanded;
        })();
        """

        config = CrawlerRunConfig(
            session_id=session_id,
            cache_mode=CacheMode.BYPASS,
            wait_until="domcontentloaded",
            wait_for="js:()=> document.querySelector('section.HcyOxe') !== null",
            virtual_scroll_config=virtual_scroll,
            js_code=expand_js,
            delay_before_return_html=2.0,
        )

        try:
            async with AsyncWebCrawler() as crawler:
                result = await crawler.arun(url=target_url, config=config)
        except Exception as exc:  # noqa: BLE001
            print(f"  ✗ showAllReviews sayfası açılamadı: {exc}")
            return None

        if not result.success or not result.html:
            print(f"  ✗ showAllReviews içerik alınamadı: {result.error_message}")
            return None

        return result.html

    async def get_reviews(
        self,
        app_id: str,
        *,
        country: Optional[str] = "us",
        language: Optional[str] = "en",
        limit: int = 10,
        sort: int = SORT_NEWEST,
    ) -> List[PlayStoreReview]:
        """Fetch Play Store reviews for the given application.
        
        Args:
            app_id: Google Play app ID (e.g., 'com.spotify.music')
            country: Country code (e.g., 'us', 'tr')
            language: Language code (e.g., 'en', 'tr')
            limit: Maximum number of reviews to fetch
            sort: Sort order - SORT_MOST_RELEVANT (1), SORT_NEWEST (2), or SORT_RATING (3)
        """

        limit = max(1, limit)
        normalized_country = (country or "us").lower()
        url_params = [f"id={app_id}"]
        if language:
            url_params.append(f"hl={language}")
        if normalized_country:
            url_params.append(f"gl={normalized_country}")
        app_url = f"https://play.google.com/store/apps/details?{'&'.join(url_params)}"

        sort_names = {
            SORT_MOST_RELEVANT: "most relevant",
            SORT_NEWEST: "newest",
            SORT_RATING: "rating"
        }
        sort_name = sort_names.get(sort, "newest")
        print(f"Fetching reviews for {app_id} (limit: {limit}, sort: {sort_name})")

        reviews: List[PlayStoreReview] = []
        try:
            api_reviews = await self._fetch_reviews_batchexecute(
                app_id,
                country=normalized_country,
                language=language,
                limit=limit,
                sort=sort,
            )
        except Exception as exc:  # noqa: BLE001
            print(f"  ✗ Batchexecute yöntemi hata verdi: {exc}")
        else:
            if api_reviews:
                reviews = api_reviews
                if len(reviews) >= limit:
                    print(f"  ✓ Batchexecute ile {len(reviews)} yorum çekildi")
                else:
                    print(f"  ⚠ Batchexecute yalnızca {len(reviews)} yorum döndürdü (istek {limit})")
            else:
                print("  ⚠ Batchexecute yanıtı yorum içermedi")

        if not reviews:
            print("  Batchexecute başarısız, showAllReviews sayfası denenecek...")
            html = await self._load_show_all_reviews_markup(app_url, app_id=app_id, limit=limit)
            if html:
                show_all_reviews = self._parse_reviews(html, limit=limit)
                if show_all_reviews:
                    reviews = show_all_reviews
                    print(f"  ✓ showAllReviews ile {len(reviews)} yorum toplandı")

        if not reviews or len(reviews) < limit:
            print("  showAllReviews başarısız, modal yaklaşımı deniyorum...")

            # First try: Modal approach
            html = await self._load_reviews_markup(app_url, app_id=app_id, limit=limit)
            if html:
                modal_reviews = self._parse_reviews(html, limit=limit)
                if modal_reviews:
                    existing = {rev.username + rev.date + rev.body for rev in reviews}
                    merged: List[PlayStoreReview] = reviews[:]
                    for rev in modal_reviews:
                        signature = rev.username + rev.date + rev.body
                        if signature not in existing:
                            merged.append(rev)
                            existing.add(signature)
                    reviews = merged
                    print(f"  ✓ Modal method found: {len(reviews)} reviews")

            # Second try: Direct fetch (non-modal)
            if len(reviews) < limit:
                print("  Modal method didn't get enough reviews, trying direct fetch...")
                html = await self._fallback_fetch_html(app_url)
                if html:
                    direct_reviews = self._parse_reviews(html, limit=limit)
                    if len(direct_reviews) > len(reviews):
                        reviews = direct_reviews
                        print(f"  ✓ Direct fetch succeeded: {len(reviews)} reviews")

        # If we got reviews but less than requested, note it
        if reviews:
            if len(reviews) < limit:
                print(f"  ⚠ Got {len(reviews)} reviews (requested {limit})")
            else:
                print(f"  ✓ Successfully got {len(reviews)} reviews")
        else:
            print("  ✗ No reviews could be extracted")

        redacted = self._redact_reviews(reviews[:limit], language=language)
        return redacted

    def _redact_reviews(
        self,
        reviews: List[PlayStoreReview],
        *,
        language: Optional[str],
    ) -> List[PlayStoreReview]:
        if not reviews:
            return reviews

        sanitized: List[PlayStoreReview] = []
        for review in reviews:
            raw_title = review.title or ""
            raw_body = review.body or ""

            redacted_title = redact_text(raw_title, language=language) if raw_title else ""
            redacted_body = redact_text(raw_body, language=language) if raw_body else ""

            analysis_title = strip_redacted_text(redacted_title)
            analysis_body = strip_redacted_text(redacted_body)

            try:
                if analysis_body or analysis_title:
                    analysis = REVIEW_ENRICHER.analyze_review(
                        body=analysis_body or "",
                        title=analysis_title or None,
                        rating=review.rating,
                        language_hint=language,
                    )
                else:
                    analysis = {}
            except Exception as exc:
                analysis = {"analysis_error": str(exc)}
            sanitized.append(
                PlayStoreReview(
                    username=review.username,
                    rating=review.rating,
                    title=redacted_title,
                    body=redacted_body,
                    date=review.date,
                    helpful_count=review.helpful_count,
                    version=review.version,
                    analysis=analysis,
                )
            )
        return sanitized

    async def _load_reviews_markup(self, url: str, *, app_id: str, limit: int) -> Optional[str]:
        """Use Crawl4AI to open the review modal and virtual-scroll its content."""

        data_dir = Path(".crawl4ai").resolve()
        data_dir.mkdir(parents=True, exist_ok=True)
        # Remove data_dir from BrowserConfig as it's not supported
        browser = BrowserConfig(headless=True, verbose=False)
        session_id = f"play-reviews-{app_id}-{uuid.uuid4().hex[:6]}"

        # Dynamic scroll count based on desired limit
        # Google Play loads ~10-20 reviews per scroll, so we need many scrolls
        scroll_count = max(150, min(400, limit * 8))  # Very aggressive scrolling
        target_count = limit  # Use the actual limit instead of capping at 200

        open_modal_config = CrawlerRunConfig(
            cache_mode=CacheMode.BYPASS,
            wait_until="domcontentloaded",
            session_id=session_id,
            js_code="""
            (() => {
                // Multiple strategies to find the reviews button
                const strategies = [
                    // Strategy 1: Look for buttons with review-related text
                    () => {
                        const candidates = Array.from(document.querySelectorAll('button, a[role="button"], div[role="button"], span[role="button"]'));
                        const normalize = (value) => (value || '').toLowerCase();
                        const keywords = ['review', 'yorum', 'bewertung', 'reseña', 'avis', 'recensione', 'recensão'];
                        const qualifiers = ['see all', 'view all', 'all reviews', 'tüm', 'alle', 'todas', 'tous', 'tutte', 'todos'];

                        for (const el of candidates) {
                            const text = normalize(el.textContent || '');
                            const aria = normalize(el.getAttribute('aria-label') || '');
                            const label = `${text} ${aria}`.trim();
                            const hasKeyword = keywords.some(k => label.includes(k));
                            const hasQualifier = qualifiers.some(k => label.includes(k)) ||
                                                label.includes('ratings') ||
                                                label.includes('reviews') ||
                                                label.includes('evaluations');

                            if (hasKeyword && (hasQualifier || label.includes('rating'))) {
                                console.log('Found review button with text:', label);
                                try {
                                    el.scrollIntoView({ behavior: 'instant', block: 'center' });
                                    setTimeout(() => el.click(), 100);
                                    return true;
                                } catch (error) {
                                    console.log('Click failed:', error);
                                    continue;
                                }
                            }
                        }
                        return false;
                    },

                    // Strategy 2: Look for specific Play Store selectors
                    () => {
                        const selectors = [
                            'button[aria-label*="reviews"]',
                            'button[aria-label*="ratings"]',
                            'a[href*="showReviews"]',
                            'div[data-g-id="ratings"] button',
                            '.XQDved',
                            '.VfPpkd-LgbsSe'
                        ];

                        for (const selector of selectors) {
                            const el = document.querySelector(selector);
                            if (el && el.offsetParent !== null) {  // Element is visible
                                console.log('Found review button with selector:', selector);
                                try {
                                    el.scrollIntoView({ behavior: 'instant', block: 'center' });
                                    setTimeout(() => el.click(), 100);
                                    return true;
                                } catch (error) {
                                    continue;
                                }
                            }
                        }
                        return false;
                    },

                    // Strategy 3: Look for expandable rating sections
                    () => {
                        const ratingsSection = document.querySelector('[data-g-id="ratings"], .EGFGHd, .jg5gSc');
                        if (ratingsSection) {
                            const buttons = ratingsSection.querySelectorAll('button, [role="button"]');
                            for (const btn of buttons) {
                                if (btn.textContent && btn.textContent.toLowerCase().includes('see')) {
                                    console.log('Found rating section button');
                                    try {
                                        btn.scrollIntoView({ behavior: 'instant', block: 'center' });
                                        setTimeout(() => btn.click(), 100);
                                        return true;
                                    } catch (error) {
                                        continue;
                                    }
                                }
                            }
                        }
                        return false;
                    }
                ];

                // Try each strategy
                for (const strategy of strategies) {
                    try {
                        if (strategy()) {
                            return true;
                        }
                    } catch (error) {
                        console.log('Strategy failed:', error);
                        continue;
                    }
                }

                console.log('No review button found, trying direct navigation');
                return false;
            })();
            """,
            wait_for=textwrap.dedent(
                """
                js:()=> {
                    const modal = document.querySelector('[aria-modal="true"], .fysCi, .VfPpkd-wzTsW');
                    if (!modal) {
                      // Also check for any large dialog that appeared
                      const dialogs = document.querySelectorAll('[role="dialog"], .bN96Pf, .Q8A9H');
                      if (dialogs.length > 0) return true;
                      return false;
                    }
                    return true;
                }
                """
            ).strip(),
            delay_before_return_html=1.0,  # Give modal time to open
        )

        # Try multiple container selectors for the modal
        container_selectors = [
            '[aria-modal="true"] :is(div.fysCi, div.VfPpkd-wzTsW)',
            '[aria-modal="true"] div.fysCi',
            '[aria-modal="true"] .VfPpkd-wzTsW',
            '[aria-modal="true"] div',
            '[role="dialog"] div',
            '[role="dialog"] div.fysCi',
            '[role="dialog"] .VfPpkd-wzTsW',
            '.bN96Pf div',
            '.Q8A9H div',
            '.bN96Pf',
            '.Q8A9H'
        ]

        virtual_scroll = VirtualScrollConfig(
            container_selector=','.join(container_selectors),
            scroll_count=scroll_count,
            scroll_by="container_height",
            wait_after_scroll=1.5,  # Balance between speed and loading time
        )

        collect_config = CrawlerRunConfig(
            session_id=session_id,
            js_only=True,
            virtual_scroll_config=virtual_scroll,
            js_code="""
            (() => {
                // First expand all "full review" buttons
                const expandTerms = ['full review', 'tam yorum', 'tüm yorumu göster', 'mehr rezension', 'reseña completa', 'leggi recensione', 'ler resenha completa', 'more', 'show more'];
                const candidates = Array.from(document.querySelectorAll('button, div[role="button"], span[role="button"]'));

                console.log('Expanding reviews...');
                let expandedCount = 0;

                for (const el of candidates) {
                    const label = ((el.textContent || '') + ' ' + (el.getAttribute('aria-label') || '')).toLowerCase();
                    if (!label) continue;

                    if (expandTerms.some(term => label.includes(term))) {
                        try {
                            el.scrollIntoView({ behavior: 'instant', block: 'center' });
                            setTimeout(() => el.click(), 100);
                            expandedCount++;
                        } catch (error) { /* ignore */ }
                    }
                }

                console.log(`Expanded ${expandedCount} reviews`);

                // Force scroll to bottom multiple times to trigger loading
                const scrollable = document.querySelector('[aria-modal="true"] div, [role="dialog"] div, .bN96Pf div, .Q8A9H div');
                if (scrollable) {
                    // Scroll down in steps to trigger lazy loading
                    for (let i = 0; i < 5; i++) {
                        setTimeout(() => {
                            scrollable.scrollTop = scrollable.scrollHeight + (i * 500);
                        }, i * 200);
                    }
                }

                // Wait a bit and check for more reviews
                setTimeout(() => {
                    const reviewElements = document.querySelectorAll('[data-review-id], div.RHo1pe, .RHo1pe');
                    console.log(`Total reviews found after expansion: ${reviewElements.length}`);
                }, 2000);

                return expandedCount;
            })();
            """,
            wait_for=textwrap.dedent(
                f"""
                js:()=> {{
                    // Check for reviews in multiple possible containers
                    const containers = [
                      document.querySelector('[aria-modal="true"]'),
                      document.querySelector('[role="dialog"]'),
                      document.querySelector('.bN96Pf'),
                      document.querySelector('.Q8A9H')
                    ].filter(c => c !== null);

                    for (const container of containers) {{
                      const reviewContainer = container.querySelector('div.fysCi, div.VfPpkd-wzTsW, div');
                      if (reviewContainer) {{
                        const items = reviewContainer.querySelectorAll('[data-review-id], header[data-review-id], div.RHo1pe, .RHo1pe');
                        console.log(`Found ${{items.length}} reviews in container`);
                        if (items.length >= {target_count}) {{
                          return true;
                        }}
                      }}
                    }}

                    // Fallback: check total reviews in the page
                    const allReviews = document.querySelectorAll('[data-review-id], div.RHo1pe, .RHo1pe');
                    console.log(`Total reviews on page: ${{allReviews.length}}`);
                    return allReviews.length >= {target_count};
                }}
                """
            ).strip(),
            cache_mode=CacheMode.BYPASS,
            wait_until="domcontentloaded",
            delay_before_return_html=1.0,  # Wait before extracting HTML
            capture_network_requests=False,
            capture_console_messages=True,  # Enable to see console logs
        )

        try:
            async with AsyncWebCrawler(config=browser) as crawler:
                print(f"  Opening reviews modal for {app_id}...")
                first_run = await crawler.arun(url=url, config=open_modal_config)
                if not first_run.success:
                    print(f"  ✗ Failed to open reviews modal: {first_run.error_message}")
                    # Try fallback method without modal
                    print("  Trying fallback method without opening modal...")
                    return await self._fallback_fetch_html(url)

                # Check if console messages show any button clicks
                if first_run.console_messages:
                    for msg in first_run.console_messages[:5]:  # Show first 5 messages
                        if 'Found review button' in str(msg) or 'console.log' in str(msg):
                            print(f"  Console: {msg}")

                print(f"  Scrolling to load reviews (target: {target_count})...")
                second_run = await crawler.arun(url=url, config=collect_config)
                if not second_run.success or not second_run.html:
                    print(f"  ✗ Failed to extract reviews: {second_run.error_message}")
                    return None

                # Log console messages from second run
                if second_run.console_messages:
                    for msg in second_run.console_messages[-5:]:  # Show last 5 messages
                        if 'Found' in str(msg) or 'Expanded' in str(msg):
                            print(f"  Console: {msg}")

                return second_run.html
        except Exception as exc:  # noqa: BLE001
            print(f"✗ Error loading reviews modal: {exc}")
            # Try fallback
            try:
                print("  Attempting fallback fetch...")
                return await self._fallback_fetch_html(url)
            except:
                return None

    async def _scrolling_fetch(self, url: str, app_id: str, limit: int) -> Optional[str]:
        """Fetch HTML with virtual scrolling to load more reviews without modal."""
        try:
            data_dir = Path(".crawl4ai").resolve()
            data_dir.mkdir(parents=True, exist_ok=True)
            browser = BrowserConfig(headless=True, verbose=False)
            session_id = f"play-scroll-{app_id}-{uuid.uuid4().hex[:6]}"

            # Scroll the reviews section directly
            virtual_scroll = VirtualScrollConfig(
                container_selector='div[data-g-id="reviews"], .EGFGHd',
                scroll_count=max(5, min(50, limit)),
                scroll_by="window",
                wait_after_scroll=1.0,
            )

            scroll_config = CrawlerRunConfig(
                session_id=session_id,
                js_code="""
                (() => {
                    // Scroll to the reviews section first
                    const reviewsSection = document.querySelector('[data-g-id="reviews"]');
                    if (reviewsSection) {
                        reviewsSection.scrollIntoView({ behavior: 'instant', block: 'start' });
                    }

                    // Expand any collapsed reviews
                    const expandButtons = document.querySelectorAll('button, [role="button"]');
                    let expanded = 0;

                    for (const btn of expandButtons) {
                        const text = (btn.textContent || '').toLowerCase();
                        if (text.includes('full') || text.includes('more')) {
                            try {
                                btn.click();
                                expanded++;
                            } catch (e) {}
                        }
                    }

                    console.log(`Expanded ${expanded} reviews before scrolling`);
                    return expanded;
                })();
                """,
                virtual_scroll_config=virtual_scroll,
                wait_for=textwrap.dedent(
                    f"""
                    js:()=> {{
                        const reviews = document.querySelectorAll('[data-review-id], div.EGFGHd');
                        return reviews.length >= {min(limit, 20)};
                    }}
                    """
                ).strip(),
                cache_mode=CacheMode.BYPASS,
                wait_until="domcontentloaded",
                delay_before_return_html=1.0,
            )

            async with AsyncWebCrawler(config=browser) as crawler:
                print(f"  Scrolling to load reviews (target: {limit})...")
                result = await crawler.arun(url=url, config=scroll_config)

                if result.success and result.html:
                    return result.html
                else:
                    print(f"  ✗ Scrolling fetch failed: {result.error_message}")
                    return None

        except Exception as exc:  # noqa: BLE001
            print(f"✗ Error with scrolling fetch: {exc}")
            return None

    async def _fallback_fetch_html(self, url: str) -> Optional[str]:
        """Fallback: fetch static HTML when modal interaction fails."""
        try:
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
        except Exception as exc:  # noqa: BLE001
            print(f"✗ Error fetching {url}: {exc}")
            return None

    def _parse_reviews(self, html: str, *, limit: int) -> List[PlayStoreReview]:
        """Extract reviews from Play Store HTML."""
        soup = BeautifulSoup(html, "html.parser")
        review_nodes = self._locate_review_nodes(soup)
        reviews: List[PlayStoreReview] = []
        seen_ids: set[str] = set()

        for raw_node in review_nodes:
            if len(reviews) >= limit:
                break
            try:
                node = self._normalize_review_node(raw_node)
                if node is None:
                    continue
                review_id = self._extract_review_id(node)
                if review_id:
                    if review_id in seen_ids:
                        continue
                    seen_ids.add(review_id)
                review = self._extract_review_from_node(node)
            except Exception as exc:  # noqa: BLE001
                print(f"  ✗ Error parsing review: {exc}")
                continue
            if review:
                reviews.append(review)

        return reviews

    def _locate_review_nodes(self, soup: BeautifulSoup) -> List[Tag]:
        """Locate review containers within the fetched HTML."""
        # Expanded list of selectors to catch various Play Store UI patterns
        selectors = [
            # Modal-based selectors (most common)
            '[aria-modal="true"] div.fysCi > div.RHo1pe',
            '[aria-modal="true"] div.VfPpkd-wzTsW > div.RHo1pe',
            '[aria-modal="true"] div.RHo1pe',
            '[aria-modal="true"] .RHo1pe',

            # Dialog-based selectors
            '[role="dialog"] div.RHo1pe',
            '[role="dialog"] .RHo1pe',
            '.bN96Pf div.RHo1pe',
            '.Q8A9H div.RHo1pe',

            # General selectors (fallback)
            "div.RHo1pe",
            '[data-review-id]',
            'header[data-review-id]',

            # Alternative container patterns
            '[aria-modal="true"] div[data-review-id]',
            '[role="dialog"] div[data-review-id]',

            # New Play Store UI patterns
            '.pa1cbe',
            '.d15Mdf',
            '.bAhLNe',
            'div[data-g-id="reviews"] div.RHo1pe',
            'div[data-g-id="reviews"] div.EGFGHd',
        ]

        for selector in selectors:
            found = soup.select(selector)
            if found:
                # Filter out duplicate elements
                unique_elements = []
                seen_ids = set()
                for el in found:
                    el_id = el.get('data-review-id') or id(el)
                    if el_id not in seen_ids:
                        seen_ids.add(el_id)
                        unique_elements.append(el)
                if unique_elements:
                    print(f"  ✓ Found {len(unique_elements)} review nodes with selector: {selector}")
                    return unique_elements

        # Final fallback - look for any review-like structure
        print("  ⚠ No standard selectors found, trying pattern matching...")
        all_divs = soup.find_all('div')
        review_like = []

        for div in all_divs:
            # Look for divs that contain typical review elements
            has_rating = div.find('div', {'aria-label': lambda x: x and 'star' in x.lower()})
            has_username = div.find(class_=lambda x: x and ('X43Kjb' in str(x) or 'X5PpBb' in str(x)))
            has_date = div.find('time') or div.find(class_=lambda x: x and 'bp9Aid' in str(x))

            if (has_rating or has_username) and has_date:
                review_like.append(div)

        if review_like:
            print(f"  ✓ Found {len(review_like)} review-like divs via pattern matching")
            return review_like[:100]  # Limit to prevent false positives

        # Last resort - look for reviews container
        container = soup.find("div", attrs={"data-g-id": "reviews"})
        if container:
            return container.find_all("div", class_="EGFGHd", recursive=False)

        print("  ✗ No review nodes found with any method")
        return []

    def _normalize_review_node(self, node: Tag) -> Optional[Tag]:
        """Ensure we always work with the review container div."""
        # Check if node itself is a review container
        if node.has_attr("data-review-id"):
            return node

        # Check for class-based containers
        if "RHo1pe" in (node.get("class") or []):
            return node

        # Check for header elements
        if node.name == "header" and node.has_attr("data-review-id"):
            # Find parent container that might have the full review
            parent = node.find_parent("div", class_="EGFGHd")
            if parent:
                return parent
            # Or just return the header itself
            return node

        # Try to find parent with review data
        parent = node.find_parent(attrs={"data-review-id": True})
        if parent:
            return parent

        parent = node.find_parent("div", class_="RHo1pe")
        if parent:
            return parent

        parent = node.find_parent("div", class_="EGFGHd")
        if parent:
            return parent

        return None

    def _extract_review_id(self, node: Tag) -> Optional[str]:
        """Derive review identifier used to deduplicate nodes."""
        if node.has_attr("data-review-id"):
            return str(node.get("data-review-id"))
        header = node.find(attrs={"data-review-id": True})
        if header:
            return str(header.get("data-review-id"))
        return None

    def _extract_review_from_node(self, node: Tag) -> Optional[PlayStoreReview]:
        """Extract structured review from a review container element."""
        text_blob = node.get_text(" ", strip=True)

        raw_username = self._extract_username(node, text_blob)
        if not raw_username:
            return None
        username = self._anonymize_user(raw_username)

        rating = self._extract_rating(node)
        date = self._extract_date(node, text_blob)
        helpful_count = self._extract_helpful_count(text_blob)
        version = self._extract_version(text_blob)

        body_text = self._extract_body(node, text_blob)
        title, body = self._split_title_and_body(body_text)

        if not title and not body:
            return None

        return PlayStoreReview(
            username=username,
            rating=rating,
            title=title,
            body=body or body_text,
            date=date,
            helpful_count=helpful_count,
            version=version,
        )

    def _extract_username(self, node: Tag, fallback_text: str) -> Optional[str]:
        """Extract username from review node."""
        # Try multiple selectors for username
        selectors = [
            ".X43Kjb",
            ".X5PpBb",
            ".gSGphe",
            ".ynVncd",
            "[data-reviewer-name]"
        ]

        for selector in selectors:
            candidate = node.select_one(selector)
            if candidate and candidate.text.strip():
                return candidate.text.strip()

        # Check if node is header and look for username inside
        if node.name == "header":
            user_span = node.find("span", class_=lambda x: x and "X43Kjb" in str(x) if x else False)
            if user_span:
                return user_span.text.strip()

        # Fallback: try to extract from text
        match = re.match(r"^([^\n]+?)\s+more_vert", fallback_text)
        if match:
            return match.group(1).strip()

        # Another fallback: look for the first text element that seems like a name
        all_spans = node.find_all("span")
        for span in all_spans:
            text = span.text.strip()
            if text and len(text) > 2 and len(text) < 30 and not any(char.isdigit() for char in text):
                # Likely a username
                return text

        return None

    def _extract_rating(self, node: Tag) -> Optional[float]:
        """Extract rating from review."""
        rating_element = node.select_one('[role="img"][aria-label]')
        if not rating_element:
            rating_element = node.select_one('[aria-label*="star"]')

        if rating_element:
            rating_label = rating_element.get("aria-label", "")
            match = re.search(r"(\d+(?:[.,]\d+)?)", rating_label)
            if match:
                value = match.group(1).replace(",", ".")
                try:
                    return float(value)
                except ValueError:
                    return None
        return None

    def _extract_date(self, node: Tag, fallback_text: str) -> str:
        """Extract review date."""
        candidate = node.select_one(".bp9Aid")
        if candidate and candidate.text.strip():
            return candidate.text.strip()

        time_tag = node.find("time")
        if time_tag and time_tag.text.strip():
            return time_tag.text.strip()

        date_pattern = (
            r"(January|February|March|April|May|June|July|August|September|October|November|December)"
            r"\s+\d{1,2},\s+\d{4}"
        )
        match = re.search(date_pattern, fallback_text)
        if match:
            return match.group(0)
        return ""

    def _extract_helpful_count(self, full_text: str) -> Optional[int]:
        """Extract helpful count from review."""
        pattern = (
            r"(\d+(?:[.,]\d+)*)\s+(?:people|person)\s+found\s+this\s+review\s+helpful"
            r"|\b(\d+(?:[.,]\d+)*)\s+found\s+this\s+helpful"
        )
        match = re.search(pattern, full_text, flags=re.IGNORECASE)

        if match:
            count_str = next(group for group in match.groups() if group)
            count_str = count_str.replace(",", "").replace(".", "")
            try:
                return int(count_str)
            except ValueError:
                return None
        return None

    def _extract_version(self, full_text: str) -> Optional[str]:
        """Extract app version from review."""
        match = re.search(r"Version\s+([\d.]+)", full_text, flags=re.IGNORECASE)
        if match:
            return match.group(1)
        return None

    def _extract_body(self, node: Tag, fallback_text: str) -> str:
        """Extract the full review body text."""
        # If node is a header, we need to look in the sibling or parent container
        if node.name == "header":
            # Look for the full review container
            parent = node.find_parent("div", class_="EGFGHd")
            if parent:
                # Try to find the review text in the parent
                text_selectors = [
                    '[jsname="fbQN7e"]',
                    '[jsname="bN97Pc"]',
                    '[data-review-text]',
                    ".h3YV2d",
                    ".Jtu6Td",
                    ".UD7Dzf",
                    ".K7oBsc",
                    ".RGJjCe",
                    ".po6LEe",
                    ".Rc2H0b"
                ]
                for selector in text_selectors:
                    candidate = parent.select_one(selector)
                    if candidate and candidate.text.strip():
                        return self._clean_review_text(candidate.get_text(" ", strip=True))

        # Standard text selectors
        text_selectors = [
            '[jsname="fbQN7e"]',
            '[jsname="bN97Pc"]',
            '[data-review-text]',
            ".h3YV2d",
            ".Jtu6Td",
            ".UD7Dzf",
            ".K7oBsc",
            ".RGJjCe",
            ".po6LEe",
            ".Rc2H0b"
        ]

        for selector in text_selectors:
            candidate = node.select_one(selector)
            if candidate and candidate.text.strip():
                return self._clean_review_text(candidate.get_text(" ", strip=True))

        # Look for divs with text content that might be the review
        all_divs = node.find_all("div")
        for div in all_divs:
            text = div.get_text(" ", strip=True)
            if text and len(text) > 20 and not any(skip in text.lower() for skip in ['star', 'rating', 'date', 'helpful']):
                return self._clean_review_text(text)

        aria_label = node.get("aria-label")
        if isinstance(aria_label, str) and aria_label.strip():
            return self._clean_review_text(aria_label)

        # Fallback: remove leading metadata.
        cleaned = self._strip_leading_metadata(fallback_text)
        return cleaned

    def _split_title_and_body(self, body_text: str) -> Tuple[str, str]:
        """Split body text into title and remaining body."""
        if not body_text:
            return "", ""

        sentences = re.split(r"(?<=[.!?])\s+", body_text)
        if len(sentences) > 1:
            title = sentences[0].strip()
            remaining = " ".join(sentences[1:]).strip()
            return title, remaining

        if len(body_text) > 160:
            return body_text[:120].strip(), body_text[120:].strip()

        return "", body_text.strip()

    def _clean_review_text(self, value: str) -> str:
        """Normalize review text by removing UI artefacts."""
        text = value or ""
        replacements = [
            r"\bFlag inappropriate\b",
            r"\bShow review history\b",
            r"\bReport inappropriate\b",
            r"\bFull Review\b",
            r"\bRead more\b",
            r"\bmore_vert\b",
            r"\bDid you find this helpful\?\b",
        ]
        for pattern in replacements:
            text = re.sub(pattern, "", text, flags=re.IGNORECASE)
        return re.sub(r"\s+", " ", text).strip()

    def _strip_leading_metadata(self, text: str) -> str:
        """Remove headers (username, rating, date) from fallback text."""
        cleaned = self._clean_review_text(text)
        if not cleaned:
            return ""

        date_pattern = (
            r"(January|February|March|April|May|June|July|August|September|October|November|December)"
            r"\s+\d{1,2},\s+\d{4}"
        )
        match = re.search(date_pattern, cleaned)
        if match:
            cleaned = cleaned[match.end():]

        cleaned = re.sub(
            r"\d+(?:[.,]\d+)*\s+(?:people|person)\s+found.*",
            "",
            cleaned,
            flags=re.IGNORECASE,
        )
        cleaned = re.sub(r"Version\s+[\d.]+.*", "", cleaned, flags=re.IGNORECASE)
        return cleaned.strip()


async def main() -> None:
    scraper = PlayStoreReviewScraper()
    reviews = await scraper.get_reviews(
        app_id="com.spotify.music",
        country="us",
        language="en",
        limit=50,
    )

    print("\n" + "=" * 80)
    print("Play Store Reviews")
    print("=" * 80)

    for i, review in enumerate(reviews, 1):
        print(f"\n{i}. {review.username}")
        if review.rating:
            print(f"   Rating: {review.rating} stars")
        print(f"   Date: {review.date}")
        print(f"   Title: {review.title}")
        print(f"   Body: {review.body[:150]}...")
        if review.helpful_count:
            print(f"   Helpful: {review.helpful_count} people")

    print("\n" + "=" * 80)


if __name__ == "__main__":
    asyncio.run(main())
