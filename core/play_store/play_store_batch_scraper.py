import asyncio
import json
import os
import re
from argparse import ArgumentParser, Namespace
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Set, Tuple

from .play_store_scraper import PlayStoreScraper
from .play_store_reviews import SORT_MOST_RELEVANT, SORT_NEWEST, SORT_RATING
from .config import settings


DEFAULT_COUNTRY = settings.default_country
DEFAULT_LANGUAGE = settings.default_language
DEFAULT_SEARCH_OUTPUT_DIR = Path(os.getenv("PLAY_STORE_SEARCH_OUTPUT_DIR", "play_store_search_results"))


def parse_args() -> Namespace:
    parser = ArgumentParser(description="Play Store JSON sonuçlarını kullanarak toplu scrape işlemi yapar.")
    parser.add_argument(
        "--input",
        nargs="+",
        required=True,
        help="JSON dosyası, klasör veya glob pattern (örn. play_store_search_results/*.json).",
    )
    parser.add_argument(
        "--country",
        default=None,
        help=f"JSON'daki ülke bilgisini ezmek için kullanılır (varsayılan: JSON değeri veya {DEFAULT_COUNTRY}).",
    )
    parser.add_argument(
        "--language",
        "--lang",
        dest="language",
        default=None,
        help=f"JSON'daki dil bilgisini ezmek için kullanılır (varsayılan: JSON değeri veya {DEFAULT_LANGUAGE}).",
    )
    parser.add_argument(
        "--summary",
        default=None,
        help=(
            "Özet JSON çıktısının kaydedileceği yol "
            "(varsayılan: play_store_search_results/<keyword>-<ülke>-<timestamp>.json)."
        ),
    )
    parser.add_argument(
        "--no-reviews",
        dest="capture_reviews",
        action="store_false",
        help="Yorumları çekme.",
    )
    parser.add_argument(
        "--reviews-limit",
        type=int,
        default=100,
        help="Maksimum çekilecek yorum sayısı (varsayılan: 100, batchexecute API ile sınırsız).",
    )
    parser.add_argument(
        "--reviews-country",
        default="us",
        help="Yorum çekilecek ülke kodu (varsayılan: us).",
    )
    parser.add_argument(
        "--reviews-language",
        default="en",
        help="Yorum dili (varsayılan: en).",
    )
    parser.add_argument(
        "--reviews-sort",
        type=str,
        choices=["most_relevant", "newest", "rating"],
        default="newest",
        help=(
            "Yorum sıralama türü: "
            "most_relevant (en alakalı), "
            "newest (en yeni), "
            "rating (puana göre). "
            "Varsayılan: newest"
        ),
    )
    parser.set_defaults(capture_reviews=True)
    return parser.parse_args()


def expand_inputs(raw_inputs: Sequence[str]) -> List[Path]:
    collected: List[Path] = []
    for raw in raw_inputs:
        candidate = Path(raw)
        if candidate.exists():
            if candidate.is_dir():
                collected.extend(sorted(p for p in candidate.glob("*.json") if p.is_file()))
            else:
                collected.append(candidate)
            continue

        globbed = sorted(Path().glob(raw))
        collected.extend(p for p in globbed if p.is_file())

    unique: Dict[Path, None] = {}
    for path in collected:
        unique[path.resolve()] = None
    return [Path(p) for p in unique.keys()]


def slugify(value: str) -> str:
    lowered = value.strip().lower()
    cleaned = re.sub(r"[^\w\-]+", "_", lowered)
    collapsed = re.sub(r"_+", "_", cleaned).strip("_")
    return collapsed or "collection"


def extract_apps_from_file(
    path: Path,
    override_country: Optional[str],
    override_language: Optional[str],
) -> List[Dict[str, str]]:
    try:
        with path.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except Exception as exc:
        print(f"✗ {path}: JSON okunamadı ({exc})")
        return []

    query = payload.get("query", {})
    country = override_country or query.get("country") or DEFAULT_COUNTRY
    language = override_language or query.get("lang") or DEFAULT_LANGUAGE

    keyword = query.get("keyword")
    if keyword:
        base_group_name = slugify(keyword)
    else:
        base_group_name = slugify(path.stem)

    group_name = base_group_name
    if country:
        group_name = f"{base_group_name}-{country.lower()}"

    apps_payload = payload.get("apps", [])
    if not isinstance(apps_payload, list):
        print(f"✗ {path}: 'apps' listesi bulunamadı.")
        return []

    apps: List[Dict[str, str]] = []
    for app in apps_payload:
        app_id_raw = app.get("app_id") or app.get("id")
        app_name = app.get("app_name") or app.get("name")
        if not app_id_raw or not app_name:
            continue
        apps.append(
            {
                "id": str(app_id_raw),
                "name": app_name,
                "country": country,
                "language": language,
                "group": group_name,
                "source_file": str(path),
                "search_keyword": keyword,
            }
        )

    if apps:
        lang_info = language or "default"
        print(
            f"✓ {path}: {len(apps)} uygulama yüklendi "
            f"(country={country}, language={lang_info}, group={group_name})"
        )
    else:
        print(f"✗ {path}: Uygulama listesi boş.")
    return apps


def load_apps_from_sources(
    paths: Iterable[Path],
    override_country: Optional[str],
    override_language: Optional[str],
) -> List[Dict[str, str]]:
    aggregated: List[Dict[str, str]] = []
    seen_keys: Set[Tuple[str, str, Optional[str], Optional[str]]] = set()

    for path in sorted(paths):
        apps = extract_apps_from_file(path, override_country, override_language)
        for app in apps:
            key = (
                app["id"],
                app["country"],
                app.get("language"),
                app.get("group"),
            )
            if key in seen_keys:
                continue
            seen_keys.add(key)
            aggregated.append(app)

    return aggregated


async def batch_scrape(args: Namespace) -> None:
    input_paths = expand_inputs(args.input)
    if not input_paths:
        print("✗ Girdi olarak kullanılacak JSON dosyası bulunamadı.")
        return
    apps = load_apps_from_sources(input_paths, args.country, args.language)
    if not apps:
        print("✗ Uygulama listesi oluşturulamadı.")
        return

    scraper = PlayStoreScraper()
    results = []

    print("=" * 60)
    print("TOPLU PLAY STORE SCRAPER")
    print("=" * 60)
    print(f"Toplam uygulama: {len(apps)}\n")

    for idx, app in enumerate(apps, start=1):
        print(f"\n[{idx}/{len(apps)}] Scraping: {app['name']}")
        print("-" * 60)
        try:
            # Map sort string to sort code
            sort_map = {
                "most_relevant": SORT_MOST_RELEVANT,
                "newest": SORT_NEWEST,
                "rating": SORT_RATING,
            }
            reviews_sort = sort_map.get(args.reviews_sort, SORT_NEWEST)
            
            result = await scraper.scrape_app(
                app_id=app["id"],
                app_name=app["name"],
                country=app["country"],
                language=app.get("language"),
                group_name=app.get("group"),
                capture_reviews=args.capture_reviews,
                reviews_limit=args.reviews_limit,
                reviews_country=args.reviews_country,
                reviews_language=args.reviews_language,
                reviews_sort=reviews_sort,
            )
            result["source_file"] = app.get("source_file")
            result["search_keyword"] = app.get("search_keyword")
            results.append(result)
            status = "✓" if not result.get("error") else "✗"
            reviews = result.get('reviews_found', 0)
            print(f"{status} Result: {reviews} reviews")
        except Exception as exc:
            print(f"✗ Error: {exc}")
            results.append(
                {
                    "app_name": app["name"],
                    "app_id": app["id"],
                    "country": app["country"],
                    "language": app.get("language"),
                    "group": app.get("group"),
                    "source_file": app.get("source_file"),
                    "search_keyword": app.get("search_keyword"),
                    "error": str(exc),
                }
            )

    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)

    total_reviews = sum(r.get("reviews_found", 0) for r in results)
    successful = sum(1 for r in results if "error" not in r)

    print(f"Toplam uygulama: {len(apps)}")
    print(f"Başarılı: {successful}")
    print(f"Başarısız: {len(apps) - successful}")
    print(f"Toplam çekilen yorum: {total_reviews}")

    print("\nDetaylar:")
    for r in results:
        status = "✓" if "error" not in r else "✗"
        lang = r.get("language") or "-"
        group = r.get("group") or "-"
        reviews = r.get("reviews_found", 0)
        rating = r.get("rating_value")
        rating_str = f"{rating:.1f}⭐" if rating else "-"
        print(f"  {status} [{group}] {r['app_name']} (lang={lang}): {rating_str} {reviews}💬")

    if args.summary:
        summary_path = Path(args.summary)
    else:
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        groups = sorted({r.get("group") for r in results if r.get("group")})
        if len(groups) == 1:
            summary_name = f"{groups[0]}_{timestamp}.json"
        elif len(groups) > 1:
            summary_name = f"{groups[0]}_plus_{len(groups) - 1}_groups_{timestamp}.json"
        else:
            summary_name = f"play_store_summary_{timestamp}.json"
        summary_path = DEFAULT_SEARCH_OUTPUT_DIR / summary_name
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    with summary_path.open("w", encoding="utf-8") as handle:
        json.dump(results, handle, indent=2, ensure_ascii=False)
        handle.write("\n")
    print(f"\n✓ Summary saved to: {summary_path}")
    print("=" * 60)


async def main() -> None:
    args = parse_args()
    await batch_scrape(args)


if __name__ == "__main__":
    asyncio.run(main())
