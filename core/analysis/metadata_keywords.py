"""Metadata keyword extraction limited to app names and descriptions."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Awaitable, Dict, List, Optional, Sequence, Tuple

from core.analysis.keyword_analysis import (
    analyze_cooccurrence,
    analyze_keyword_frequency,
    analyze_ngrams,
)
from core.app_store.app_store_search import AppStoreSearchClient
from core.app_store.app_store_simple_scraper import (
    AppStoreScraper as SimpleAppStoreScraper,
)
from core.app_store.locale_utils import default_language_for_country
from core.play_store.play_store_search import PlayStoreSearchClient
from core.play_store.play_store_scraper import PlayStoreScraper
from core.privacy import strip_redacted_text


@dataclass
class MetadataKeywordRequest:
    """Configuration for the metadata keyword workflow."""

    keyword: str
    limit: int = 10
    include_app_store: bool = True
    include_play_store: bool = True
    app_store_country: str = "US"
    app_store_language: Optional[str] = None
    play_store_country: str = "US"
    play_store_language: Optional[str] = None


@dataclass
class StoreProcessingResult:
    """Internal payload for each store before serialization."""

    store_key: str
    payload: Dict[str, Any]
    names: List[str]
    descriptions: List[str]


class MetadataKeywordAnalyzer:
    """Fetches store search results and extracts only metadata keywords."""

    def __init__(self, *, concurrency: int = 4) -> None:
        self._concurrency = max(1, concurrency)
        self._app_store_client = AppStoreSearchClient()
        self._app_store_scraper = SimpleAppStoreScraper()
        self._play_store_client = PlayStoreSearchClient()
        self._play_store_scraper = PlayStoreScraper()

    async def run(self, request: MetadataKeywordRequest) -> Dict[str, Any]:
        if not request.include_app_store and not request.include_play_store:
            raise ValueError("En az bir store seçilmelidir.")

        tasks = []
        if request.include_app_store:
            tasks.append(self._process_app_store(request))
        if request.include_play_store:
            tasks.append(self._process_play_store(request))

        store_results = await asyncio.gather(*tasks)

        stores_payload: Dict[str, Any] = {}
        combined_names: List[str] = []
        combined_descriptions: List[str] = []

        app_store_language = request.app_store_language or default_language_for_country(
            request.app_store_country,
            "en",
        )
        play_store_language = request.play_store_language or default_language_for_country(
            request.play_store_country,
            "en",
        )

        for result in store_results:
            stores_payload[result.store_key] = result.payload
            combined_names.extend(result.names)
            combined_descriptions.extend(result.descriptions)

        query_meta: Dict[str, Any] = {
            "keyword": request.keyword,
            "limit": request.limit,
            "stores": list(stores_payload.keys()),
        }
        if request.include_app_store:
            query_meta["app_store"] = {
                "country": request.app_store_country,
                "language": app_store_language,
            }
        if request.include_play_store:
            query_meta["play_store"] = {
                "country": request.play_store_country,
                "language": play_store_language,
            }

        response = {
            "query": query_meta,
            "analyzed_at": datetime.now(timezone.utc).isoformat(),
            "stores": stores_payload,
            "combined_keyword_analysis": {
                "names": self._build_keyword_summary(combined_names, min_length=2),
                "descriptions": self._build_keyword_summary(combined_descriptions, min_length=3),
            },
            "global_stats": {
                "total_apps": sum(
                    payload["stats"].get("apps_found", 0)
                    for payload in stores_payload.values()
                ),
                "names_collected": len(combined_names),
                "descriptions_collected": len(combined_descriptions),
            },
        }

        return response

    async def _process_app_store(self, request: MetadataKeywordRequest) -> StoreProcessingResult:
        country = request.app_store_country.upper()
        language = (
            request.app_store_language
            or default_language_for_country(country, "en")
        )

        apps = await self._app_store_client.search(
            request.keyword,
            country=country,
            limit=request.limit,
            lang=language,
        )
        names = self._collect_app_names(apps)
        descriptions, failures = await self._fetch_app_store_descriptions(
            apps,
            country=country.lower(),
        )

        payload = self._build_store_payload(
            store_key="app_store",
            names=names,
            descriptions=descriptions,
            apps_found=len(apps),
            detail_failures=failures,
            meta={"country": country, "language": language},
        )
        return StoreProcessingResult(
            store_key="app_store",
            payload=payload,
            names=names,
            descriptions=descriptions,
        )

    async def _process_play_store(self, request: MetadataKeywordRequest) -> StoreProcessingResult:
        country = request.play_store_country.upper()
        language = request.play_store_language or default_language_for_country(
            country,
            "en",
        )

        apps = await self._play_store_client.search(
            request.keyword,
            country=country,
            language=language,
            limit=request.limit,
        )
        names = self._collect_app_names(apps)
        descriptions, failures = await self._fetch_play_store_descriptions(
            apps,
            country=country.lower(),
            language=language,
        )

        payload = self._build_store_payload(
            store_key="play_store",
            names=names,
            descriptions=descriptions,
            apps_found=len(apps),
            detail_failures=failures,
            meta={"country": country, "language": language},
        )
        return StoreProcessingResult(
            store_key="play_store",
            payload=payload,
            names=names,
            descriptions=descriptions,
        )

    async def _fetch_app_store_descriptions(
        self,
        apps: Sequence[Dict[str, Any]],
        *,
        country: str,
    ) -> Tuple[List[str], int]:
        coroutines = [
            self._app_store_scraper.fetch_app_details(str(app.get("app_id")), country=country)
            for app in apps
            if app.get("app_id") is not None
        ]
        responses, failures = await self._gather_with_limiter(coroutines)
        descriptions: List[str] = []
        for response in responses:
            if not response:
                continue
            desc = response.get("app_description") or response.get("description")
            if not desc:
                continue
            clean_desc = strip_redacted_text(str(desc))
            if clean_desc:
                descriptions.append(clean_desc)
        return descriptions, failures

    async def _fetch_play_store_descriptions(
        self,
        apps: Sequence[Dict[str, Any]],
        *,
        country: str,
        language: Optional[str],
    ) -> Tuple[List[str], int]:
        coroutines = [
            self._play_store_scraper.get_app_details(
                str(app.get("app_id")),
                country=country,
                language=language,
            )
            for app in apps
            if app.get("app_id")
        ]
        responses, failures = await self._gather_with_limiter(coroutines)
        descriptions: List[str] = []
        for response in responses:
            if not response:
                continue
            desc = getattr(response, "description", None) or getattr(
                response, "app_description", None
            )
            if not desc:
                continue
            clean_desc = strip_redacted_text(str(desc))
            if clean_desc:
                descriptions.append(clean_desc)
        return descriptions, failures

    async def _gather_with_limiter(
        self, coroutines: Sequence[Awaitable[Any]]
    ) -> Tuple[List[Any], int]:
        if not coroutines:
            return [], 0

        semaphore = asyncio.Semaphore(self._concurrency)
        results: List[Any] = []
        failures = 0

        async def runner(coro: Awaitable[Any]) -> Any:
            async with semaphore:
                try:
                    return await coro
                except Exception as exc:  # pragma: no cover - defensive logging
                    return exc

        responses = await asyncio.gather(*(runner(coro) for coro in coroutines))
        for response in responses:
            if isinstance(response, Exception):
                failures += 1
            else:
                results.append(response)
        return results, failures

    def _build_store_payload(
        self,
        *,
        store_key: str,
        names: List[str],
        descriptions: List[str],
        apps_found: int,
        detail_failures: int,
        meta: Dict[str, Any],
    ) -> Dict[str, Any]:
        name_summary = self._build_keyword_summary(names, min_length=2)
        description_summary = self._build_keyword_summary(descriptions, min_length=3)
        return {
            "store": store_key,
            "meta": meta,
            "stats": {
                "apps_found": apps_found,
                "names_collected": len(names),
                "descriptions_collected": len(descriptions),
                "detail_failures": detail_failures,
            },
            "keyword_analysis": {
                "names": name_summary,
                "descriptions": description_summary,
            },
        }

    @staticmethod
    def _collect_app_names(apps: Sequence[Dict[str, Any]]) -> List[str]:
        names: List[str] = []
        for app in apps:
            raw_name = app.get("app_name") or app.get("name")
            if not raw_name:
                continue
            clean_name = strip_redacted_text(str(raw_name))
            if clean_name:
                names.append(clean_name)
        return names

    def _build_keyword_summary(self, texts: List[str], *, min_length: int) -> Dict[str, Any]:
        if not texts:
            return {
                "top_keywords": {},
                "bigrams": {},
                "trigrams": {},
                "cooccurrence": {},
            }

        return {
            "top_keywords": analyze_keyword_frequency(
                texts,
                top_n=30,
                min_length=min_length,
            ),
            "bigrams": analyze_ngrams(
                texts,
                n=2,
                top_n=20,
                min_length=min_length,
            ),
            "trigrams": analyze_ngrams(
                texts,
                n=3,
                top_n=15,
                min_length=min_length,
            ),
            "cooccurrence": analyze_cooccurrence(
                texts,
                window_size=5,
                top_n=20,
                min_length=min_length,
            ),
        }
