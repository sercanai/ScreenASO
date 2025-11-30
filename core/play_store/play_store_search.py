"""CLI utility to search Google Play Store applications via Crawl4AI."""

from __future__ import annotations

import asyncio
import json
import os
import re
from argparse import ArgumentParser, Namespace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set
from urllib.parse import quote_plus

from bs4 import BeautifulSoup
from crawl4ai import AsyncWebCrawler

from .config import settings


PLAY_STORE_SEARCH_URL = "https://play.google.com/store/search"
DEFAULT_COUNTRY = settings.default_country
DEFAULT_LANGUAGE = settings.default_language
DEFAULT_OUTPUT_DIR = Path(os.getenv("PLAY_STORE_SEARCH_OUTPUT_DIR", "play_store_search_results"))


class PlayStoreSearchError(Exception):
    """Raised when the Play Store search page cannot be processed."""


def _build_search_url(keyword: str, *, country: str, language: Optional[str]) -> str:
    params = [f"q={quote_plus(keyword)}", "c=apps"]
    if language:
        params.append(f"hl={language}")
    if country:
        params.append(f"gl={country}")
    return f"{PLAY_STORE_SEARCH_URL}?{'&'.join(params)}"


def _parse_rating_value(label: str) -> Optional[float]:
    match = re.search(r"([0-9]+(?:\.[0-9]+)?)", label)
    if not match:
        return None
    try:
        return float(match.group(1))
    except ValueError:
        return None


def _parse_int(text: str) -> Optional[int]:
    cleaned = text.replace(",", "").replace(".", "")
    match = re.search(r"([0-9]+)", cleaned)
    if not match:
        return None
    try:
        return int(match.group(1))
    except ValueError:
        return None


class PlayStoreSearchClient:
    """Async search client that scrapes the Play Store search UI."""

    async def search(
        self,
        keyword: str,
        *,
        country: str = DEFAULT_COUNTRY,
        language: Optional[str] = DEFAULT_LANGUAGE,
        limit: int = 25,
    ) -> List[Dict[str, Any]]:
        if not keyword.strip():
            raise ValueError("Arama anahtar kelimesi boş olamaz.")

        search_url = _build_search_url(keyword, country=country, language=language)
        async with AsyncWebCrawler() as crawler:
            result = await crawler.arun(
                url=search_url,
                wait_until="networkidle",
                bypass_cache=True,
                headers={"User-Agent": "Mozilla/5.0"},
            )
        if not result.success or not result.html:
            raise PlayStoreSearchError(f"Sayfa yüklenemedi: {search_url}")

        apps = self._parse_search_results(result.html, limit=limit)
        print(f"✓ {len(apps)} uygulama bulundu ({keyword})")
        return apps

    def _parse_search_results(self, html: str, *, limit: int) -> List[Dict[str, Any]]:
        soup = BeautifulSoup(html, "html.parser")
        anchors = soup.find_all("a", href=re.compile(r"/store/apps/details\?id="))

        results: List[Dict[str, Any]] = []
        seen_ids: Set[str] = set()

        for anchor in anchors:
            href = anchor.get("href")
            if not href:
                continue
            match = re.search(r"id=([^&]+)", href)
            if not match:
                continue
            app_id = match.group(1)
            if app_id in seen_ids:
                continue
            app_url = f"https://play.google.com{href}" if href.startswith("/") else href

            name = anchor.get("aria-label")
            if not name:
                name = next((text.strip() for text in anchor.stripped_strings if text.strip()), None)
            if not name:
                continue

            card_container = anchor
            for parent in anchor.parents:
                if parent.name == "div" and parent.get("role") in {"listitem", "presentation"}:
                    card_container = parent
                    break

            developer = None
            developer_el = card_container.find("div", attrs={"class": re.compile(r"(VZUsy|cXFu1)")})
            if developer_el:
                developer = developer_el.get_text(strip=True) or None

            rating_value = None
            rating_count = None

            rating_el = card_container.find(attrs={"aria-label": re.compile("Rated", re.IGNORECASE)})
            if rating_el and rating_el.has_attr("aria-label"):
                rating_value = _parse_rating_value(rating_el["aria-label"])

            count_el = card_container.find(attrs={"aria-label": re.compile("ratings", re.IGNORECASE)})
            if count_el and count_el.has_attr("aria-label"):
                rating_count = _parse_int(count_el["aria-label"])

            icon_url = None
            icon_el = anchor.find("img")
            if icon_el:
                icon_url = icon_el.get("src") or icon_el.get("data-src")

            results.append(
                {
                    "app_id": app_id,
                    "app_name": name,
                    "app_store_url": app_url,
                    "developer": developer,
                    "icon_url": icon_url,
                    "user_rating": rating_value,
                    "user_rating_count": rating_count,
                }
            )
            seen_ids.add(app_id)
            if len(results) >= limit:
                break

        return results


def slugify(text: str) -> str:
    cleaned = "".join(ch.lower() if ch.isalnum() else "_" for ch in text)
    collapsed = "_".join(segment for segment in cleaned.split("_") if segment)
    return collapsed or "results"


def build_output_path(
    keyword: str,
    output_dir: Path,
    filename: Optional[str],
    country: Optional[str] = None,
) -> Path:
    if filename:
        target = Path(filename)
        if not target.suffix:
            target = target.with_suffix(".json")
        if not target.is_absolute():
            target = output_dir / target
        return target

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    default_name = f"{slugify(keyword)}_{timestamp}"
    if country:
        default_name = f"{default_name}-{country.lower()}"
    default_name = f"{default_name}.json"
    return output_dir / default_name


def save_results(payload: Dict[str, Any], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, ensure_ascii=False)
        handle.write("\n")
    print(f"✓ Sonuç kaydedildi: {output_path}")


async def run_search(args: Namespace) -> None:
    client = PlayStoreSearchClient()
    try:
        apps = await client.search(
            args.keyword,
            country=args.country,
            language=args.lang,
            limit=args.limit,
        )
    except PlayStoreSearchError as exc:
        print(f"✗ Arama başarısız: {exc}")
        return
    except ValueError as exc:
        print(f"✗ Geçersiz parametre: {exc}")
        return

    payload = {
        "query": {
            "keyword": args.keyword,
            "country": args.country,
            "limit": args.limit,
            "lang": args.lang,
        },
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "apps": apps,
    }

    output_dir = Path(args.output_dir or DEFAULT_OUTPUT_DIR)
    output_path = build_output_path(args.keyword, output_dir, args.output, args.country)
    save_results(payload, output_path)


def parse_args() -> Namespace:
    parser = ArgumentParser(description="Google Play Store arama sonuçlarını JSON olarak kaydeder.")
    parser.add_argument("--keyword", required=True, help="Aranacak anahtar kelime.")
    parser.add_argument(
        "--country",
        default=DEFAULT_COUNTRY,
        help=f"Ülke kodu (varsayılan: {DEFAULT_COUNTRY}).",
    )
    parser.add_argument("--limit", type=int, default=25, help="Maksimum sonuç sayısı (varsayılan: 25).")
    parser.add_argument(
        "--lang",
        default=DEFAULT_LANGUAGE,
        help=f"Dil parametresi (varsayılan: {DEFAULT_LANGUAGE}).",
    )
    parser.add_argument(
        "--output-dir",
        default=str(DEFAULT_OUTPUT_DIR),
        help=f"JSON dosyasının kaydedileceği klasör (varsayılan: {DEFAULT_OUTPUT_DIR}).",
    )
    parser.add_argument(
        "--output",
        default=None,
        help="Çıktı dosya adı (opsiyonel). Uzantı verilmezse .json eklenir.",
    )
    return parser.parse_args()


async def main() -> None:
    args = parse_args()
    await run_search(args)


if __name__ == "__main__":
    asyncio.run(main())
