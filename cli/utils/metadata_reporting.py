"""Markdown report generator for metadata keyword analyses."""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Tuple


STORE_LABELS = {
    "app_store": "App Store",
    "play_store": "Play Store",
}


def build_metadata_keyword_report(data: Dict[str, Any], *, top_n: int = 15) -> str:
    """Return a Markdown report string for metadata keyword JSON outputs."""
    lines: List[str] = []
    query = data.get("query", {})
    stores = data.get("stores", {}) or {}
    analyzed_at = data.get("analyzed_at")

    lines.append("# Metadata Keyword Report")
    lines.append("")
    lines.append(_format_query_section(query, analyzed_at))

    global_stats = data.get("global_stats") or {}
    if global_stats:
        lines.append("## Global Stats")
        lines.append(_format_metric_table(global_stats.items()))

    for store_key, payload in stores.items():
        label = STORE_LABELS.get(store_key, store_key.replace("_", " ").title())
        lines.append(f"## {label}")
        stats = payload.get("stats") or {}
        if stats:
            lines.append("### Summary")
            lines.append(_format_metric_table(stats.items()))

        keyword_analysis = payload.get("keyword_analysis") or {}
        if keyword_analysis:
            lines.append(_format_keyword_sections("Name Keywords", keyword_analysis.get("names"), top_n))
            lines.append(
                _format_keyword_sections(
                    "Description Keywords",
                    keyword_analysis.get("descriptions"),
                    top_n,
                )
            )

    combined = data.get("combined_keyword_analysis") or {}
    if combined:
        lines.append("## Combined Keyword Analysis")
        lines.append(_format_keyword_sections("Name Keywords", combined.get("names"), top_n))
        lines.append(
            _format_keyword_sections(
                "Description Keywords", combined.get("descriptions"), top_n
            )
        )

    return "\n".join(line.rstrip() for line in lines if line is not None).strip() + "\n"


def _format_query_section(query: Dict[str, Any], analyzed_at: Any) -> str:
    lines = []
    keyword = query.get("keyword", "-")
    limit = query.get("limit", "-")
    stores = query.get("stores") or []
    lines.append(f"- **Keyword:** {keyword}")
    lines.append(f"- **Limit:** {limit}")
    if stores:
        lines.append(
            "- **Stores:** "
            + ", ".join(STORE_LABELS.get(store, store.replace("_", " ").title()) for store in stores)
        )
    if analyzed_at:
        lines.append(f"- **Generated:** {analyzed_at}")
    app_store_meta = query.get("app_store")
    play_store_meta = query.get("play_store")
    if app_store_meta:
        lines.append(
            f"- **App Store Locale:** {app_store_meta.get('country', '-')} / "
            f"{app_store_meta.get('language', '-') }"
        )
    if play_store_meta:
        lines.append(
            f"- **Play Store Locale:** {play_store_meta.get('country', '-')} / "
            f"{play_store_meta.get('language', '-') }"
        )
    return "\n".join(lines) + "\n"


def _format_keyword_sections(title: str, payload: Dict[str, Any], top_n: int) -> str:
    if not payload:
        return f"### {title}\n> No data.\n"

    sections: List[str] = [f"### {title}"]
    sections.append(
        _format_keyword_table("Top Keywords", payload.get("top_keywords") or {}, top_n)
    )
    sections.append(
        _format_keyword_table("Bigrams", payload.get("bigrams") or {}, top_n)
    )
    sections.append(
        _format_keyword_table("Trigrams", payload.get("trigrams") or {}, top_n)
    )
    sections.append(
        _format_keyword_table("Co-occurrence", payload.get("cooccurrence") or {}, top_n)
    )
    return "\n".join(sections)


def _format_keyword_table(title: str, data: Dict[str, int], limit: int) -> str:
    if not data:
        return f"#### {title}\n> Veri yok.\n"

    rows = list(data.items())[:limit]
    header = ["#### {title}", "", "| Keyword | Count |", "| --- | ---: |"]
    table_rows = [f"| {key} | {value} |" for key, value in rows]
    return "\n".join([header[0].format(title=title)] + header[1:] + table_rows + [""])


def _format_metric_table(items: Iterable[Tuple[Any, Any]]) -> str:
    pairs = [(str(k).replace("_", " ").title(), v) for k, v in items]
    if not pairs:
        return "> No data.\n"
    lines = ["| Metric | Value |", "| --- | ---: |"]
    lines.extend(f"| {key} | {value} |" for key, value in pairs)
    lines.append("")
    return "\n".join(lines)
