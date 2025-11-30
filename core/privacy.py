"""Utilities for masking personally identifiable information (PII) in text."""

from __future__ import annotations

import importlib.util
import os
import re
import tempfile
import threading
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Optional, Sequence, Tuple


def _resolve_tld_cache_dir() -> Path:
    """Choose a writable cache dir for tldextract (PyInstaller-safe)."""
    env_candidates = (
        os.environ.get("TLD_CACHE_DIR"),
        os.environ.get("TLD_EXTRACT_CACHE"),
        os.environ.get("TLDEXTRACT_CACHE"),
    )
    for candidate in env_candidates:
        if candidate:
            return Path(candidate).expanduser().resolve()

    base = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")).expanduser()
    return (base / "tldextract").resolve()


def _ensure_cache_dir() -> Path:
    for path in (_resolve_tld_cache_dir(), Path(tempfile.gettempdir()) / "tldextract"):
        try:
            path.mkdir(parents=True, exist_ok=True)
            return path
        except Exception:
            continue
    return Path(".")  # Fallback; unlikely to reach.


TLD_CACHE_DIR = _ensure_cache_dir()
os.environ.setdefault("TLD_CACHE_DIR", str(TLD_CACHE_DIR))
os.environ.setdefault("TLD_EXTRACT_CACHE", str(TLD_CACHE_DIR))
os.environ.setdefault("TLD_FALLBACK_TO_NETWORK", "0")
os.environ.setdefault("TLD_EXTRACT_FALLBACK_TO_NETWORK", "0")
os.environ.setdefault("TLDEXTRACT_CACHE", str(TLD_CACHE_DIR))

try:
    from presidio_analyzer import AnalyzerEngine, RecognizerResult  # type: ignore
    from presidio_analyzer.nlp_engine import NlpEngineProvider  # type: ignore
    from presidio_anonymizer import AnonymizerEngine  # type: ignore
    from presidio_anonymizer.entities import OperatorConfig  # type: ignore
except ImportError:  # pragma: no cover - optional dependency
    AnalyzerEngine = None  # type: ignore[assignment]
    NlpEngineProvider = None  # type: ignore[assignment]
    AnonymizerEngine = None  # type: ignore[assignment]
    OperatorConfig = None  # type: ignore[assignment]
    RecognizerResult = None  # type: ignore[assignment]

try:  # pragma: no cover - optional dependency
    from fast_langdetect import detect as _fast_detect  # type: ignore
except ImportError:  # pragma: no cover
    _fast_detect = None  # type: ignore[assignment]


REDACTED_TOKEN = "[REDACTED]"
SUPPORTED_LANGUAGE_PREFIX = "en"
SUPPORTED_ENTITIES = (
    "PERSON",
    "LOCATION",
    "EMAIL_ADDRESS",
    "PHONE_NUMBER",
    "CREDIT_CARD",
)
SPACY_MODEL_CANDIDATES = ("en_core_web_sm", "en_core_web_md", "en_core_web_lg")
_EMAIL_PATTERN = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_PHONE_PATTERN = re.compile(
    r"(?:(?:\+?\d{1,3}[-.\s]*)?(?:\(?\d{3}\)?[-.\s]*)\d{3}[-.\s]*\d{4})"
)
_CREDIT_CARD_PATTERN = re.compile(r"\b(?:\d[ -]*?){13,16}\b")
REDACTED_REVIEW_PLACEHOLDER = "[REDACTED]"
DEFAULT_REVIEW_FIELDS = ("title", "body", "author", "reply_to", "email")
DEFAULT_REVIEW_LIST_KEYS = ("reviews", "enriched_reviews")
_REDACTED_PLACEHOLDER_PATTERN = re.compile(
    rf"^{re.escape(REDACTED_REVIEW_PLACEHOLDER)}(?:_[A-Z0-9]+)?$"
)


def _normalize_text_for_detection(text: str) -> str:
    """Normalize whitespace for language detection."""
    if not text:
        return ""
    normalized = re.sub(r"\s+", " ", text).strip()
    return normalized


def _detect_language(text: str) -> Optional[str]:
    """Detect language using fast-langdetect when available."""
    if _fast_detect is None:
        return None
    normalized = _normalize_text_for_detection(text)
    if not normalized:
        return None
    try:
        results = _fast_detect(normalized)
    except Exception:
        return None
    if not results or not isinstance(results, list):
        return None
    first = results[0]
    if not isinstance(first, dict):
        return None
    language = first.get("lang")
    if not isinstance(language, str):
        return None
    return language.lower()


@dataclass
class _PresidioResources:
    analyzer: AnalyzerEngine  # type: ignore[type-arg]
    anonymizer: AnonymizerEngine  # type: ignore[type-arg]


class _PiiRedactor:
    """Lazy Presidio-backed redactor with lightweight regex fallback."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._resources: Optional[_PresidioResources] = None

    def redact(self, text: str, *, language: Optional[str] = None) -> str:
        if not text:
            return text

        normalized_language = language or _detect_language(text)
        if normalized_language and self._language_supported(normalized_language):
            resources = self._ensure_resources()
            if resources is None:
                return self._regex_redact(text)
            analyzer_results = resources.analyzer.analyze(  # type: ignore[call-arg]
                text=text,
                language=SUPPORTED_LANGUAGE_PREFIX,
                entities=list(SUPPORTED_ENTITIES),
                return_decision_process=False,
            )

            filtered_results = self._filter_results(analyzer_results)

            if filtered_results:
                operators = None
                if OperatorConfig is not None:
                    operators = {
                        "DEFAULT": OperatorConfig(
                            "replace", {"new_value": REDACTED_TOKEN}
                        )  # type: ignore[call-arg]
                    }

                anonymized = resources.anonymizer.anonymize(  # type: ignore[call-arg]
                    text=text,
                    analyzer_results=filtered_results,
                    operators=operators,
                )

                if anonymized:
                    return anonymized.text
        return self._regex_redact(text)

    def _language_supported(self, language: Optional[str]) -> bool:
        if not language:
            return False
        normalized = language.lower()
        return normalized.startswith(SUPPORTED_LANGUAGE_PREFIX)

    def _ensure_resources(self) -> Optional[_PresidioResources]:
        if self._resources is not None:
            return self._resources

        if AnalyzerEngine is None or AnonymizerEngine is None or NlpEngineProvider is None:
            return None

        with self._lock:
            if self._resources is not None:
                return self._resources

            model_name = self._resolve_spacy_model()
            configuration = {
                "nlp_engine_name": "spacy",
                "models": [
                    {"lang_code": SUPPORTED_LANGUAGE_PREFIX, "model_name": model_name}
                ],
            }

            try:
                provider = NlpEngineProvider(nlp_configuration=configuration)  # type: ignore[call-arg]
                nlp_engine = provider.create_engine()  # type: ignore[union-attr]
                analyzer = AnalyzerEngine(  # type: ignore[call-arg]
                    nlp_engine=nlp_engine,
                    supported_languages=[SUPPORTED_LANGUAGE_PREFIX],
                )
                anonymizer = AnonymizerEngine()  # type: ignore[call-arg]
            except Exception:
                return None

            self._resources = _PresidioResources(
                analyzer=analyzer,
                anonymizer=anonymizer,
            )
            return self._resources

    def _regex_redact(self, text: str) -> str:
        """Fallback masking when Presidio is unavailable."""
        masked = _EMAIL_PATTERN.sub(REDACTED_TOKEN, text)
        masked = _PHONE_PATTERN.sub(REDACTED_TOKEN, masked)
        masked = _CREDIT_CARD_PATTERN.sub(REDACTED_TOKEN, masked)
        return masked

    @staticmethod
    def _resolve_spacy_model() -> str:
        for candidate in SPACY_MODEL_CANDIDATES:
            if importlib.util.find_spec(candidate) is not None:
                return candidate
        return SPACY_MODEL_CANDIDATES[0]

    def _filter_results(self, results: list) -> list:
        """Limit Presidio hits to reduce false positives."""
        if not results:
            return []

        filtered = []
        for result in results:
            entity_type = getattr(result, "entity_type", None)
            if entity_type not in SUPPORTED_ENTITIES:
                continue

            score = getattr(result, "score", 0.0) or 0.0
            start = getattr(result, "start", 0)
            end = getattr(result, "end", 0)
            span_length = max(0, int(end) - int(start))

            if entity_type in {"PERSON", "LOCATION"}:
                # Skip very short or low-confidence matches (brand/word false positives)
                if score < 0.70:
                    continue
                if span_length < 3:
                    continue

            filtered.append(result)

        return filtered


_GLOBAL_REDACTOR = _PiiRedactor()


def redact_text(text: str, *, language: Optional[str] = None) -> str:
    """Mask PII content in text if English is detected."""
    return _GLOBAL_REDACTOR.redact(text, language=language)


def sanitize_reviews_for_output(
    payload: Any,
    *,
    list_keys: Sequence[str] = DEFAULT_REVIEW_LIST_KEYS,
    fields: Sequence[str] = DEFAULT_REVIEW_FIELDS,
    placeholder: str = REDACTED_REVIEW_PLACEHOLDER,
) -> Any:
    """Return a deep-copied payload where review `title`/`body` fields are masked.

    Args:
        payload: Arbitrary JSON-like structure containing review lists.
        list_keys: Dict keys that should be treated as review collections.
        fields: Review fields to sanitize within each review dict.
        placeholder: Base placeholder used before appending the field name.
    """
    cloned = deepcopy(payload)
    _sanitize_review_lists(
        cloned,
        tuple(list_keys),
        tuple(fields),
        placeholder,
    )
    return cloned


def _sanitize_review_lists(
    node: Any,
    list_keys: Tuple[str, ...],
    fields: Tuple[str, ...],
    placeholder: str,
) -> None:
    if isinstance(node, dict):
        for key, value in node.items():
            if key in list_keys and isinstance(value, list):
                _mask_reviews(value, fields, placeholder)
            else:
                _sanitize_review_lists(value, list_keys, fields, placeholder)
    elif isinstance(node, list):
        for item in node:
            _sanitize_review_lists(item, list_keys, fields, placeholder)


def _mask_reviews(
    reviews: Iterable[Any],
    fields: Tuple[str, ...],
    placeholder: str,
) -> None:
    for review in reviews:
        if not isinstance(review, dict):
            continue
        for field in fields:
            value = review.get(field)
            target = f"{placeholder}_{field.upper()}"
            if isinstance(value, str) and value and value != target:
                review[field] = target


def is_redacted_value(value: Optional[str]) -> bool:
    """Return True when value represents a fully redacted placeholder."""
    if not isinstance(value, str):
        return False
    normalized = value.strip()
    if not normalized:
        return False
    if normalized == REDACTED_TOKEN:
        return True
    return bool(_REDACTED_PLACEHOLDER_PATTERN.match(normalized))


def strip_redacted_text(value: Optional[str]) -> str:
    """Remove placeholder tokens and return cleaned text."""
    if not isinstance(value, str):
        return ""
    normalized = value.strip()
    if not normalized or is_redacted_value(normalized):
        return ""
    cleaned = normalized.replace(REDACTED_TOKEN, " ")
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned
