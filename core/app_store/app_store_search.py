import asyncio
import json
from argparse import ArgumentParser, Namespace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

import aiohttp

from .config import settings
from .locale_utils import default_language_for_country


API_URL = "https://itunes.apple.com/search"
DEFAULT_MEDIA = "software"
DEFAULT_ENTITY = "software"
DEVICE_ENTITY_MAP = {
    "iphone": "software",
    "ipad": "iPadSoftware",
    "mac": "macSoftware",
    "all": "software,iPadSoftware,macSoftware",
}
DEFAULT_DEVICE = (
    settings.default_device
    if settings.default_device in DEVICE_ENTITY_MAP
    else "iphone"
)
DEFAULT_OUTPUT_DIR = settings.search_output_dir
DEFAULT_LANGUAGE = settings.default_language
DEFAULT_COUNTRY = settings.default_country
REQUEST_TIMEOUT = aiohttp.ClientTimeout(total=15)


class AppStoreSearchError(Exception):
    """Özel hata sınıfı: Apple Search API isteği başarısız oldu."""


class AppStoreSearchClient:
    """Apple Search API üzerinden uygulama arayan async istemci."""

    def __init__(
        self, base_url: str = API_URL, timeout: Optional[aiohttp.ClientTimeout] = None
    ) -> None:
        self.base_url = base_url
        self.timeout = timeout or REQUEST_TIMEOUT

    async def search(
        self,
        keyword: str,
        *,
        country: str = DEFAULT_COUNTRY,
        limit: int = 25,
        media: str = DEFAULT_MEDIA,
        entity: Optional[str] = None,
        lang: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Keyword ile App Store uygulamalarını döndür."""
        if not keyword.strip():
            raise ValueError("Arama anahtar kelimesi boş olamaz.")

        resolved_entity = entity or DEFAULT_ENTITY

        params = {
            "term": keyword,
            "country": country,
            "media": media,
            "entity": resolved_entity,
            "limit": str(limit),
        }
        if lang:
            params["lang"] = lang

        async with aiohttp.ClientSession(timeout=self.timeout) as session:
            try:
                async with session.get(
                    self.base_url, params=params
                ) as response:
                    if response.status != 200:
                        text = await response.text()
                        raise AppStoreSearchError(
                            f"HTTP {response.status}: {text[:120]}"
                        )
                    payload = await response.json(content_type=None)
            except asyncio.TimeoutError as exc:
                raise AppStoreSearchError("İstek zaman aşımına uğradı.") from exc
            except aiohttp.ClientError as exc:
                raise AppStoreSearchError(f"Ağ hatası: {exc}") from exc
            except json.JSONDecodeError as exc:
                raise AppStoreSearchError("JSON yanıtı çözümlenemedi.") from exc

        raw_results = payload.get("results", [])
        normalized = self._normalize_results(raw_results)
        print(f"✓ {len(normalized)} uygulama bulundu ({keyword})")
        return normalized

    def _normalize_results(self, results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """API sonuçlarını hedef JSON formatına dönüştür."""
        seen_ids: Set[int] = set()
        normalized: List[Dict[str, Any]] = []

        for item in results:
            kind = item.get("kind")
            if kind not in {"software"}:
                continue
            app_id = item.get("trackId")
            app_name = item.get("trackName")
            app_url = item.get("trackViewUrl")

            if not app_id or not app_name or not app_url:
                continue
            if app_id in seen_ids:
                continue

            seen_ids.add(app_id)

            rating = item.get("averageUserRating")
            if rating is None:
                rating = item.get("averageUserRatingForCurrentVersion")
            rating_count = item.get("userRatingCount") or item.get(
                "userRatingCountForCurrentVersion"
            )

            # Apple Search API'den gelen rating değerini koru, Crawl4AI varsa üzerine yazar.
            normalized.append(
                {
                    "app_id": app_id,
                    "app_name": app_name,
                    "app_store_url": app_url,
                    "user_rating": rating,
                    "user_rating_count": rating_count,
                }
            )

        return normalized


def slugify(text: str) -> str:
    """Basit slug üretimi (alfanümerik olmayanları alt çizgi yapar)."""
    cleaned = "".join(char.lower() if char.isalnum() else "_" for char in text)
    collapsed = "_".join(segment for segment in cleaned.split("_") if segment)
    return collapsed or "results"


def build_output_path(keyword: str, output_dir: Path, filename: Optional[str]) -> Path:
    """Sonuç JSON dosyasının kaydedileceği yolu hazırla."""
    if filename:
        target = Path(filename)
        if not target.suffix:
            target = target.with_suffix(".json")
        if not target.is_absolute():
            target = output_dir / target
        return target

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    default_name = f"{slugify(keyword)}_{timestamp}.json"
    return output_dir / default_name


def save_results(payload: Dict[str, Any], output_path: Path) -> None:
    """JSON sonucunu diske yaz."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, ensure_ascii=False)
        handle.write("\n")
    print(f"✓ Sonuç kaydedildi: {output_path}")


async def run_search(args: Namespace) -> None:
    """CLI üzerinden arama çalıştır."""
    client = AppStoreSearchClient()
    entity_value = args.entity or DEVICE_ENTITY_MAP.get(args.device, DEFAULT_ENTITY)
    resolved_lang = args.lang or default_language_for_country(
        args.country, DEFAULT_LANGUAGE
    )

    try:
        apps = await client.search(
            args.keyword,
            country=args.country,
            limit=args.limit,
            media=args.media,
            entity=entity_value,
            lang=resolved_lang,
        )
    except AppStoreSearchError as exc:
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
            "media": args.media,
            "entity": entity_value,
            "device": args.device,
            "lang": resolved_lang,
        },
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "apps": apps,
    }

    output_dir = Path(args.output_dir or DEFAULT_OUTPUT_DIR)
    output_path = build_output_path(args.keyword, output_dir, args.output)
    save_results(payload, output_path)


def parse_args() -> Namespace:
    """Komut satırı argümanlarını oluştur."""
    parser = ArgumentParser(
        description="Apple App Store arama sonuçlarını JSON olarak kaydeder."
    )
    parser.add_argument("--keyword", required=True, help="Aranacak anahtar kelime.")
    parser.add_argument(
        "--country",
        default=DEFAULT_COUNTRY,
        help=f"Ülke kodu (varsayılan: {DEFAULT_COUNTRY}).",
    )
    parser.add_argument(
        "--limit", type=int, default=25, help="Maksimum sonuç sayısı (varsayılan: 25)."
    )
    parser.add_argument(
        "--media",
        default=DEFAULT_MEDIA,
        help="Media parametresi (varsayılan: software).",
    )
    parser.add_argument(
        "--entity",
        default=None,
        help="Entity parametresi (opsiyonel). Belirtilmezse --device üzerinden ayarlanır.",
    )
    parser.add_argument(
        "--device",
        choices=list(DEVICE_ENTITY_MAP.keys()),
        default=DEFAULT_DEVICE,
        help=f"Hedef cihaz türü (varsayılan: {DEFAULT_DEVICE}).",
    )
    parser.add_argument(
        "--lang",
        default=None,
        help=(
            "Dil parametresi (varsayılan: ülkeye göre otomatik belirlenir;"
            f" örn. {DEFAULT_COUNTRY} → {default_language_for_country(DEFAULT_COUNTRY, DEFAULT_LANGUAGE)})."
        ),
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
    """Async giriş noktası."""
    args = parse_args()
    await run_search(args)


if __name__ == "__main__":
    asyncio.run(main())
