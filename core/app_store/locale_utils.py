"""Helper utilities for resolving default language/locale values by country."""

from __future__ import annotations

from typing import Optional


COUNTRY_LANGUAGE_MAP = {
    "us": "en",
    "gb": "en",
    "ca": "en",
    "au": "en",
    "nz": "en",
    "tr": "tr",
    "de": "de",
    "fr": "fr",
    "it": "it",
    "es": "es",
    "mx": "es",
    "ar": "es",
    "cl": "es",
    "co": "es",
    "pe": "es",
    "br": "pt",
    "pt": "pt",
    "nl": "nl",
    "be": "nl",
    "se": "sv",
    "no": "no",
    "dk": "da",
    "fi": "fi",
    "pl": "pl",
    "cz": "cs",
    "hu": "hu",
    "gr": "el",
    "ro": "ro",
    "sk": "sk",
    "jp": "ja",
    "kr": "ko",
    "cn": "zh",
    "tw": "zh",
    "hk": "zh",
    "sg": "en",
    "in": "en",
    "id": "id",
    "my": "ms",
    "th": "th",
    "vn": "vi",
    "ru": "ru",
    "ua": "uk",
    "ae": "ar",
    "sa": "ar",
    "qa": "ar",
    "kw": "ar",
    "il": "he",
    "za": "en",
}


def default_language_for_country(country: Optional[str], fallback: str = "en") -> str:
    if not country:
        return fallback
    return COUNTRY_LANGUAGE_MAP.get(country.lower(), fallback)


def default_locale_for_country(
    country: Optional[str],
    fallback_locale: str = "en-us",
    fallback_language: Optional[str] = None,
) -> str:
    if not country:
        return fallback_locale
    language = default_language_for_country(country, fallback_language or fallback_locale.split("-")[0])
    return f"{language}-{country.lower()}"


def compose_locale_key(language: Optional[str], country: Optional[str]) -> str:
    lang = (language or "").strip().replace("_", "-").lower()
    country_code = (country or "").strip().lower()

    parts = [segment for segment in lang.split("-") if segment]
    if not parts and country_code:
        parts = [country_code]

    if country_code:
        if not parts:
            parts = [country_code]
        if len(parts) == 1:
            if parts[0] != country_code:
                parts.append(country_code)
            else:
                parts = [parts[0], country_code]
        elif parts[-1] != country_code:
            parts.append(country_code)

    if not parts:
        return country_code
    return "-".join(parts)


__all__ = [
    "default_language_for_country",
    "default_locale_for_country",
    "compose_locale_key",
]
