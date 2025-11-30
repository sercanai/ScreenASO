"""Helper utilities to convert CLI outputs into PDF reports."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from core.pdf_report_generator import PDFReportGenerator


def generate_pdf_report(
    data: Dict[str, Any],
    output_path: Path,
    title: str = "Screen ASO Analysis Report",
) -> Path:
    """Generate a PDF report from arbitrary CLI payloads."""
    output_file = Path(output_path)
    output_file.parent.mkdir(parents=True, exist_ok=True)

    generator = PDFReportGenerator()
    apps = _collect_apps(data)

    if apps:
        if len(apps) == 1 and _has_analysis_payload(apps[0]):
            summary, sentiment_data, keyword_data = _build_sections_from_app(apps[0])
            generator.generate_report(summary, sentiment_data, keyword_data, output_file)
        else:
            generator.generate_multi_app_analysis_report(apps, output_file, title=title)
        return output_file

    app_payload = data.get("app") if isinstance(data.get("app"), dict) else data
    summary, sentiment_data, keyword_data = _build_sections_from_app(app_payload or {})
    generator.generate_report(summary, sentiment_data, keyword_data, output_file)
    return output_file


def _collect_apps(data: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Extract a list of app dictionaries from known collection keys."""
    candidates: List[Dict[str, Any]] = []

    for key in ("apps", "results"):
        payload = data.get(key)
        if not isinstance(payload, list):
            continue

        extracted: List[Dict[str, Any]] = []
        for item in payload:
            if not isinstance(item, dict):
                continue
            if isinstance(item.get("app"), dict):
                extracted.append(item["app"])
            else:
                extracted.append(item)

        if extracted:
            candidates = extracted
            break

    return candidates


def _has_analysis_payload(app: Dict[str, Any]) -> bool:
    """Check whether the entry already contains enriched analysis fields."""
    analysis_keys = {
        "sentiment",
        "review_analysis",
        "enriched_reviews",
        "keyword_analysis",
        "analysis",
        "review_stats",
        "ratings",
    }
    return any(key in app for key in analysis_keys)


def _pick_first(*values: Any) -> Any:
    """Return the first non-empty value while preserving zeros."""
    for value in values:
        if value is None:
            continue
        if isinstance(value, str) and not value.strip():
            continue
        return value
    return None


def _coerce_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _coerce_int(value: Any, default: int = 0) -> int:
    try:
        if value is None:
            return default
        return int(value)
    except (TypeError, ValueError):
        return default


def _prepare_keyword_data(source: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Normalize keyword analysis dictionaries to the structure expected by the PDF generator."""
    base = {
        "analysis": {
            "description": {"top_keywords": {}, "bigrams": {}, "trigrams": {}},
            "reviews": {"top_keywords": {}, "bigrams": {}, "trigrams": {}},
            "comparison": {"common_keywords": {}},
        }
    }

    if not isinstance(source, dict):
        return base

    analysis = source.get("analysis") if "analysis" in source else source

    for key in ("description", "reviews", "comparison"):
        value = analysis.get(key) if isinstance(analysis, dict) else None
        if isinstance(value, dict):
            base["analysis"][key] = value

    return base


def _build_sections_from_app(
    app: Dict[str, Any],
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """Convert a single app payload into sections consumed by the PDF renderer."""
    app = app or {}
    app_info = app.get("app_info") or {}
    raw_data = app.get("raw_data") or {}

    reviews_list = (
        app.get("enriched_reviews")
        or app.get("reviews")
        or raw_data.get("reviews")
        or []
    )

    resolved_app_id = str(
        _pick_first(
            app.get("app_id"),
            raw_data.get("app_id"),
            app_info.get("app_id"),
            app.get("id"),
        )
        or "unknown"
    )

    detected_store = (
        "Play Store"
        if ("." in resolved_app_id and not resolved_app_id.isdigit())
        else "App Store"
    )

    summary = {
        "app_id": resolved_app_id,
        "app_name": _pick_first(
            app.get("app_name"),
            app_info.get("name"),
            raw_data.get("app_name"),
            app.get("name"),
        )
        or "Unknown App",
        "developer": _pick_first(
            app_info.get("developer"),
            app.get("developer"),
            raw_data.get("developer"),
        )
        or "Unknown Developer",
        "rating": _coerce_float(
            _pick_first(
                app_info.get("rating"),
                app.get("rating"),
                app.get("rating_value"),
                raw_data.get("rating_value"),
                (app.get("ratings") or {}).get("average"),
                app.get("user_rating"),
            ),
            0.0,
        ),
        "rating_count": _coerce_int(
            _pick_first(
                app_info.get("rating_count"),
                app.get("rating_count"),
                raw_data.get("rating_count"),
                (app.get("ratings") or {}).get("count"),
                app.get("user_rating_count"),
            ),
            0,
        ),
        "store": _pick_first(
            app.get("store"),
            raw_data.get("store"),
            detected_store,
        )
        or detected_store,
        "country": _pick_first(
            app.get("country"),
            raw_data.get("country"),
        )
        or "",
        "language": _pick_first(
            app.get("language"),
            raw_data.get("language"),
        )
        or "",
        "analysis_date": _pick_first(
            app.get("analyzed_at"),
            raw_data.get("analyzed_at"),
        ),
    }

    summary["reviews_analyzed"] = _coerce_int(
        _pick_first(
            (app.get("review_analysis") or {}).get("total_reviews"),
            app.get("total_reviews"),
            app.get("reviews_found"),
            (app.get("review_stats") or {}).get("total_analyzed"),
            len(reviews_list),
        ),
        len(reviews_list),
    )

    sentiment_data = {
        "reviews": reviews_list,
        "sentiment": (app.get("review_analysis") or {}).get("sentiment")
        or app.get("sentiment")
        or {},
        "review_types": (app.get("review_analysis") or {}).get("review_types")
        or app.get("review_types")
        or {},
    }
    sentiment_data.update(
        {
            "store": summary.get("store", detected_store),
            "country": (summary.get("country") or raw_data.get("country") or "").upper(),
            "language": (summary.get("language") or raw_data.get("language") or "").upper(),
        }
    )

    summary["sentiment"] = sentiment_data["sentiment"]
    summary["review_types"] = sentiment_data["review_types"]

    keyword_source = (
        app.get("keyword_analysis")
        or raw_data.get("keyword_analysis")
        or app.get("analysis")
    )
    keyword_data = _prepare_keyword_data(keyword_source)

    desc_keywords = list(
        keyword_data["analysis"]["description"].get("top_keywords", {}).keys()
    )
    review_keywords = list(
        keyword_data["analysis"]["reviews"].get("top_keywords", {}).keys()
    )
    common_keywords = list(
        keyword_data["analysis"]["comparison"].get("common_keywords", {}).keys()
    )

    summary["top_keywords_description"] = desc_keywords
    summary["top_keywords_reviews"] = review_keywords
    summary["common_keywords"] = common_keywords

    return summary, sentiment_data, keyword_data
