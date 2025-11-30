from __future__ import annotations

import math
import os
import re
import unicodedata
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

try:  # pragma: no cover - optional dependency
    from fast_langdetect import detect as fast_detect  # type: ignore
except ImportError:  # pragma: no cover - optional dependency
    fast_detect = None  # type: ignore[assignment]

try:  # pragma: no cover - optional dependency
    from transformers import Pipeline, pipeline as hf_pipeline  # type: ignore
except ImportError:  # pragma: no cover - optional dependency
    Pipeline = None  # type: ignore[assignment]
    hf_pipeline = None  # type: ignore[assignment]

try:  # pragma: no cover - optional dependency
    from keybert import KeyBERT  # type: ignore
except ImportError:  # pragma: no cover - optional dependency
    KeyBERT = None  # type: ignore[assignment]

try:  # pragma: no cover - optional dependency
    from sklearn.feature_extraction.text import CountVectorizer, TfidfVectorizer  # type: ignore
except ImportError:  # pragma: no cover - optional dependency
    CountVectorizer = None  # type: ignore[assignment]
    TfidfVectorizer = None  # type: ignore[assignment]


DEFAULT_ASPECT_LABELS = (
    "performance",
    "stability",
    "pricing",
    "ads",
    "ux",
    "support",
    "content",
    "login",
)

ASPECT_KEYWORDS: Dict[str, Tuple[str, ...]] = {
    "performance": (
        "slow",
        "lag",
        "laggy",
        "delay",
        "freez",
        "loading",
        "sluggish",
        "responsive",
        "speed",
    ),
    "stability": (
        "crash",
        "bug",
        "error",
        "hang",
        "force close",
        "frozen",
        "unstable",
        "glitch",
    ),
    "pricing": (
        "price",
        "paywall",
        "subscription",
        "expensive",
        "overcharged",
        "refund",
        "billing",
    ),
    "ads": (
        "ads",
        "advert",
        "commercial",
        "pop-up",
        "popup",
        "sponsored",
    ),
    "ux": (
        "ui",
        "ux",
        "design",
        "interface",
        "navigation",
        "layout",
        "button",
        "screen",
    ),
    "support": (
        "support",
        "help",
        "customer service",
        "contact",
        "reply",
        "response",
    ),
    "content": (
        "content",
        "feature",
        "option",
        "tool",
        "template",
        "library",
    ),
    "login": (
        "login",
        "log in",
        "sign in",
        "sign-in",
        "password",
        "account",
    ),
}

FEATURE_PHRASE_CANDIDATES = (
    "dark mode",
    "offline mode",
    "export to pdf",
    "multi language",
    "multi-language",
    "keyboard support",
    "cloud sync",
    "backup",
    "integration",
    "widget",
    "notification",
)

FEATURE_PATTERNS = (
    r"\bplease add\b",
    r"\bi wish\b",
    r"\bit would be (?:great|nice)\b",
    r"\bcan you add\b",
    r"\bneed(?:s)? (?:a|the)?\b",
    r"\badd (?:an?|the)?\s+[a-z0-9 ]+",
    r"\bfeature request\b",
)

BUG_PATTERNS = (
    r"\bcrash",
    r"\bbug",
    r"\berror",
    r"\bissue",
    r"\bglitch",
    r"\bfail",
)

UX_PATTERNS = (
    r"\bui\b",
    r"\bux\b",
    r"\bdesign\b",
    r"\binterface\b",
    r"\bnavigation\b",
    r"\blayout\b",
)

PRAISE_PATTERNS = (
    r"\blove\b",
    r"\bgreat\b",
    r"\bawesome\b",
    r"\bamazing\b",
    r"\bexcellent\b",
    r"\bthank you\b",
)

PAYMENT_PATTERNS = (
    r"\bbilling\b",
    r"\bpurchase\b",
    r"\bsubscription\b",
    r"\bcharged\b",
    r"\brefund\b",
)

PERSONA_KEYWORDS: Dict[str, Tuple[str, ...]] = {
    "student": ("student", "exam", "homework", "school", "university", "class"),
    "teacher": ("teacher", "classroom", "lecture", "teaching"),
    "freelancer": ("freelancer", "client", "gig", "freelance"),
    "small_business": ("store", "business", "company", "customer", "invoice", "receipt"),
    "parent": ("kid", "child", "family", "parent"),
}

USE_CASE_KEYWORDS: Dict[str, Tuple[str, ...]] = {
    "study": ("study", "exam", "homework", "notes", "lecture"),
    "finance": ("invoice", "receipt", "expense", "budget"),
    "productivity": ("workflow", "task", "project", "organize"),
    "creative": ("design", "draw", "sketch", "creative"),
    "communication": ("chat", "message", "share", "collaborate"),
}

COMPETITOR_KEYWORDS = (
    "camscanner",
    "adobescan",
    "notion",
    "evernote",
    "onenote",
    "dropbox",
    "google drive",
    "asana",
    "slack",
)


def _normalize_whitespace(text: str) -> str:
    collapsed = re.sub(r"\s+", " ", text)
    return collapsed.strip()


def _ensure_dependency(name: str, package: Optional[object]) -> None:
    if package is None:
        raise RuntimeError(
            f"{name} bağımlılığı yüklü değil. `pip install -r requirements.txt` komutunu çalıştırın."
        )


def _strip_accents(text: str) -> str:
    normalized = unicodedata.normalize("NFKD", text)
    return "".join(ch for ch in normalized if not unicodedata.combining(ch))


def _to_lower_ascii(text: str) -> str:
    stripped = _strip_accents(text)
    return stripped.lower()


def _score_to_label(score: float) -> str:
    if score >= 0.25:
        return "positive"
    if score <= -0.25:
        return "negative"
    return "neutral"


def _safe_float(value: float) -> float:
    if math.isnan(value) or math.isinf(value):
        return 0.0
    return float(value)


@dataclass
class ReviewEnricherConfig:
    """Pipeline yapılandırması."""

    min_language_confidence: float = 0.55
    sentiment_model: str = "distilbert/distilbert-base-uncased-finetuned-sst-2-english"
    zero_shot_model: str = "facebook/bart-large-mnli"
    zero_shot_threshold: float = 0.45
    keybert_model: str = "all-MiniLM-L6-v2"
    keyword_ngram_range: Tuple[int, int] = (1, 2)
    keyword_limit: int = 8
    value_phrase_limit: int = 5
    enable_zero_shot: bool = True

    def __post_init__(self) -> None:
        if not (0.0 < self.min_language_confidence <= 1.0):
            raise ValueError("min_language_confidence 0-1 arasında olmalı")
        if self.keyword_ngram_range[0] < 1 or self.keyword_ngram_range[0] > self.keyword_ngram_range[1]:
            raise ValueError("keyword_ngram_range geçersiz")
        if self.keyword_limit <= 0:
            raise ValueError("keyword_limit pozitif olmalı")
        if self.value_phrase_limit <= 0:
            raise ValueError("value_phrase_limit pozitif olmalı")


class _LanguageDetector:
    def __init__(self, config: ReviewEnricherConfig) -> None:
        self._config = config

    def detect(self, text: str) -> Optional[Tuple[str, float]]:
        normalized = _normalize_whitespace(text)
        if not normalized:
            return None
        _ensure_dependency("fast-langdetect", fast_detect)
        
        try:
            results = fast_detect(normalized)
            if not results or not isinstance(results, list) or len(results) == 0:
                return None
            
            result = results[0]  # Get first detection
            language = result.get("lang")
            score = _safe_float(float(result.get("score", 0.0)))
            
            if not language or score < self._config.min_language_confidence:
                return None
            
            return language, score
        except Exception:
            return None


class _SentimentAnalyzer:
    def __init__(self, model_name: str) -> None:
        self._model_name = model_name
        self._pipeline: Optional[Pipeline] = None

    def analyze(self, text: str) -> Dict[str, float | str]:
        normalized = _normalize_whitespace(text)
        if not normalized:
            return {"label": "neutral", "score": 0.0, "confidence": 0.0}
        pipe = self._ensure_pipeline()
        results = pipe(normalized, truncation=True)  # type: ignore[call-arg]
        
        # Pipeline returns a list, get first result
        if isinstance(results, list) and len(results) > 0:
            result = results[0]
        else:
            result = results
            
        raw_label = str(result.get("label", "")).strip().lower()
        score = _safe_float(float(result.get("score", 0.0)))

        if "pos" in raw_label:
            signed_score = score
            label = "positive"
        elif "neg" in raw_label:
            signed_score = -score
            label = "negative"
        else:
            signed_score = 0.0
            label = "neutral"

        return {"label": label, "score": signed_score, "confidence": score}

    def _ensure_pipeline(self) -> Pipeline:
        if self._pipeline is not None:
            return self._pipeline
        _ensure_dependency("transformers", hf_pipeline)
        self._pipeline = hf_pipeline(
            "sentiment-analysis",
            model=self._model_name,
        )
        return self._pipeline


class _ZeroShotClassifier:
    def __init__(self, model_name: str) -> None:
        self._model_name = model_name
        self._pipeline: Optional[Pipeline] = None

    def classify(self, text: str, *, labels: Sequence[str], threshold: float) -> Dict[str, float]:
        normalized = _normalize_whitespace(text)
        if not normalized:
            return {}
        pipe = self._ensure_pipeline()
        result = pipe(normalized, candidate_labels=list(labels), multi_label=True)  # type: ignore[call-arg]
        scores = dict(zip(result.get("labels", []), result.get("scores", [])))
        filtered: Dict[str, float] = {}
        for label, score in scores.items():
            numeric = _safe_float(float(score))
            if numeric >= threshold:
                filtered[label] = numeric
        return filtered

    def _ensure_pipeline(self) -> Pipeline:
        if self._pipeline is not None:
            return self._pipeline
        _ensure_dependency("transformers", hf_pipeline)
        self._pipeline = hf_pipeline("zero-shot-classification", model=self._model_name)
        return self._pipeline


class _KeywordExtractor:
    def __init__(self, *, ngram_range: Tuple[int, int], limit: int) -> None:
        self._ngram_range = ngram_range
        self._limit = limit

    def extract_candidates(self, text: str) -> List[str]:
        normalized = _normalize_whitespace(text)
        if not normalized:
            return []
        _ensure_dependency("scikit-learn", CountVectorizer)
        
        # Suppress sklearn warnings for edge cases
        import warnings
        with warnings.catch_warnings():
            warnings.filterwarnings("ignore", category=RuntimeWarning)
            
            vectorizer = CountVectorizer(
                ngram_range=self._ngram_range,
                stop_words="english",
                min_df=1,
                max_features=100,  # Limit features to avoid memory issues
            )
            try:
                counts = vectorizer.fit_transform([normalized])
            except (ValueError, RuntimeWarning):
                return []
            
            if not counts.shape[1]:
                return []
            
            frequencies = counts.toarray()[0]
            feature_names = vectorizer.get_feature_names_out()

            scored = list(zip(feature_names, frequencies))
            scored.sort(key=lambda item: (-item[1], -len(item[0])))

            keywords: List[str] = []
            for token, _ in scored:
                cleaned = token.strip()
                if not cleaned:
                    continue
                keywords.append(cleaned)
                if len(keywords) >= self._limit:
                    break
            return keywords


class _ValuePhraseExtractor:
    def __init__(self, model_name: str, limit: int) -> None:
        self._model_name = model_name
        self._limit = limit
        self._model: Optional[KeyBERT] = None

    def extract(self, text: str) -> List[str]:
        normalized = _normalize_whitespace(text)
        if not normalized:
            return []
        model = self._ensure_model()
        
        # Suppress warnings from embedding calculations
        import warnings
        with warnings.catch_warnings():
            warnings.filterwarnings("ignore", category=RuntimeWarning)
            
            try:
                phrases = model.extract_keywords(
                    normalized,
                    top_n=self._limit,
                    keyphrase_ngram_range=(1, 3),
                )
            except Exception:
                return []
            
            distinct: List[str] = []
            for phrase, score in phrases:
                if not phrase:
                    continue
                cleaned = phrase.strip()
                if cleaned and cleaned not in distinct:
                    distinct.append(cleaned)
            return distinct

    def _ensure_model(self) -> KeyBERT:
        if self._model is not None:
            return self._model
        _ensure_dependency("keybert", KeyBERT)
        self._model = KeyBERT(model=self._model_name)
        return self._model


def _match_patterns(text: str, patterns: Sequence[str]) -> bool:
    return any(re.search(pattern, text, flags=re.IGNORECASE) for pattern in patterns)


def _collect_keywords(text: str, keywords: Iterable[str]) -> List[str]:
    lowered = _to_lower_ascii(text)
    matches = []
    for keyword in keywords:
        keyword_lower = keyword.lower()
        if keyword_lower in lowered:
            matches.append(keyword)
    return matches


def _merge_labels(
    heuristic: Iterable[str],
    model_scores: Dict[str, float],
    threshold: float,
) -> Dict[str, Dict[str, float | str]]:
    combined: Dict[str, Dict[str, float | str]] = {}
    for label in heuristic:
        combined[label] = {"confidence": 1.0, "source": "heuristic"}
    for label, score in model_scores.items():
        if score < threshold:
            continue
        payload = combined.setdefault(label, {"confidence": 0.0, "source": "zero-shot"})
        if score > float(payload.get("confidence", 0.0)):
            payload["confidence"] = score
            payload["source"] = "zero-shot"
    return combined


class ReviewEnricher:
    """Yorumları dil, duygu ve aksiyon etiketleriyle zenginleştirir."""

    def __init__(self, config: Optional[ReviewEnricherConfig] = None) -> None:
        self._config = config or ReviewEnricherConfig()
        self._language_detector = _LanguageDetector(self._config)
        self._sentiment_analyzer = _SentimentAnalyzer(self._config.sentiment_model)
        self._keyword_extractor = _KeywordExtractor(
            ngram_range=self._config.keyword_ngram_range,
            limit=self._config.keyword_limit,
        )
        self._value_phrase_extractor = _ValuePhraseExtractor(
            self._config.keybert_model,
            self._config.value_phrase_limit,
        )
        self._zero_shot_classifier: Optional[_ZeroShotClassifier] = None

    def analyze_text(self, text: str) -> Dict[str, object]:
        """Simple sentiment analysis for a text."""
        return self._sentiment_analyzer.analyze(text)

    def analyze_review(
        self,
        *,
        body: str,
        title: Optional[str] = None,
        rating: Optional[float] = None,
        language_hint: Optional[str] = None,
    ) -> Dict[str, object]:
        text = _normalize_whitespace(" ".join(filter(None, [title, body])))
        language = self._detect_language(text, hint=language_hint)
        sentiment = self._sentiment_analyzer.analyze(text)
        keywords = self._keyword_extractor.extract_candidates(text)
        value_phrases = self._value_phrase_extractor.extract(text)

        aspect_payload = self._detect_aspects(text, sentiment_score=float(sentiment["score"]))
        feature_tags = self._detect_feature_requests(text, keywords)
        persona_tags = self._detect_keyword_tags(text, PERSONA_KEYWORDS)
        use_case_tags = self._detect_keyword_tags(text, USE_CASE_KEYWORDS)
        competitor_mentions = _collect_keywords(text, COMPETITOR_KEYWORDS)

        review_type = self._classify_review_type(text, sentiment, rating)
        needs_reply = self._should_reply(review_type, sentiment, rating)

        return {
            "language": language,
            "sentiment_label": sentiment["label"],
            "sentiment_score": float(sentiment["score"]),
            "sentiment_confidence": float(sentiment["confidence"]),
            "aspect_sentiment": aspect_payload,
            "keyword_candidates": keywords,
            "value_phrases": value_phrases,
            "feature_request_tags": feature_tags,
            "persona_tags": persona_tags,
            "use_case_tags": use_case_tags,
            "competitor_mentions": competitor_mentions,
            "needs_reply": needs_reply,
            "review_type": review_type,
        }

    def _detect_language(self, text: str, *, hint: Optional[str]) -> Optional[str]:
        detected = self._language_detector.detect(text)
        if detected:
            return detected[0]
        if hint:
            normalized_hint = hint.lower().replace("_", "-")
            return normalized_hint.split("-")[0]
        return None

    def _get_zero_shot(self) -> Optional[_ZeroShotClassifier]:
        if not self._config.enable_zero_shot:
            return None
        if self._zero_shot_classifier is None:
            self._zero_shot_classifier = _ZeroShotClassifier(self._config.zero_shot_model)
        return self._zero_shot_classifier

    def _detect_aspects(self, text: str, *, sentiment_score: float) -> Dict[str, Dict[str, object]]:
        heuristic_matches: List[str] = []
        lowered = _to_lower_ascii(text)
        for aspect, keywords in ASPECT_KEYWORDS.items():
            if any(keyword in lowered for keyword in keywords):
                heuristic_matches.append(aspect)

        model_scores: Dict[str, float] = {}
        zero_shot = self._get_zero_shot()
        if zero_shot is not None:
            try:
                model_scores = zero_shot.classify(
                    text,
                    labels=DEFAULT_ASPECT_LABELS,
                    threshold=self._config.zero_shot_threshold,
                )
            except Exception:
                model_scores = {}

        combined = _merge_labels(heuristic_matches, model_scores, self._config.zero_shot_threshold)
        aspect_payload: Dict[str, Dict[str, object]] = {}

        for label, meta in combined.items():
            label_score = float(meta.get("confidence", 0.0))
            aspect_payload[label] = {
                "label": _score_to_label(sentiment_score),
                "score": sentiment_score,
                "confidence": label_score,
                "source": meta.get("source", "heuristic"),
            }
        return aspect_payload

    def _detect_feature_requests(self, text: str, keywords: Sequence[str]) -> List[str]:
        matches: List[str] = []
        if _match_patterns(text, FEATURE_PATTERNS):
            matches.extend(keywords[:3])
        for candidate in FEATURE_PHRASE_CANDIDATES:
            if candidate in text.lower():
                matches.append(candidate)
        distinct = []
        for item in matches:
            cleaned = item.strip().lower()
            if cleaned and cleaned not in distinct:
                distinct.append(cleaned)
        return distinct

    @staticmethod
    def _detect_keyword_tags(text: str, dictionary: Dict[str, Tuple[str, ...]]) -> List[str]:
        matches: List[str] = []
        for label, keywords in dictionary.items():
            keyword_hits = _collect_keywords(text, keywords)
            if keyword_hits:
                matches.append(label)
        return matches

    def _classify_review_type(
        self,
        text: str,
        sentiment: Dict[str, object],
        rating: Optional[float],
    ) -> str:
        lowered = text.lower()
        if _match_patterns(lowered, BUG_PATTERNS):
            return "bug_report"
        if _match_patterns(lowered, FEATURE_PATTERNS):
            return "feature_request"
        if _match_patterns(lowered, UX_PATTERNS):
            return "ux_feedback"
        if _match_patterns(lowered, PAYMENT_PATTERNS):
            return "payment_issue"
        if _match_patterns(lowered, PRAISE_PATTERNS) and sentiment.get("label") == "positive":
            return "praise"
        if rating is not None and rating >= 4 and sentiment.get("label") == "positive":
            return "praise"
        return "general_feedback"

    @staticmethod
    def _should_reply(
        review_type: str,
        sentiment: Dict[str, object],
        rating: Optional[float],
    ) -> bool:
        label = str(sentiment.get("label"))
        score = float(sentiment.get("score", 0.0))
        if review_type in {"bug_report", "feature_request", "payment_issue"}:
            return True
        if rating is not None and rating <= 2:
            return True
        if label == "negative" or score <= -0.25:
            return True
        return False


# Alias for backward compatibility
SentimentAnalyzer = ReviewEnricher
