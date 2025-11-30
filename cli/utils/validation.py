"""Validation utilities for Screen ASO."""

import re
from typing import Optional

from rich.console import Console


class ValidationError(Exception):
    """Custom validation error."""

    pass


class Validator:
    """Input validation utilities."""

    def __init__(self):
        self.console = Console()

    def validate_app_id(self, app_id: str) -> str:
        """Validate app ID format."""
        if not app_id:
            raise ValidationError("App ID cannot be empty")

        # Basic format check (e.g., com.example.app)
        if not re.match(r"^[a-zA-Z0-9._]+$", app_id):
            raise ValidationError("Invalid app ID format")

        return app_id

    def validate_country_code(self, country: str) -> str:
        """Validate country code."""
        if not country:
            return "US"  # Default

        country = country.upper()
        if not re.match(r"^[A-Z]{2}$", country):
            raise ValidationError("Country code must be 2 letters (e.g., US, TR)")

        return country

    def validate_limit(self, limit: int) -> int:
        """Validate limit parameter."""
        if limit <= 0:
            raise ValidationError("Limit must be positive")
        if limit > 1000:
            raise ValidationError("Limit cannot exceed 1000")

        return limit

    def validate_file_exists(self, filepath: str) -> str:
        """Validate that file exists."""
        from pathlib import Path

        path = Path(filepath)
        if not path.exists():
            raise ValidationError(f"File not found: {filepath}")

        if not path.is_file():
            raise ValidationError(f"Path is not a file: {filepath}")

        return str(path.absolute())

    def validate_keyword(self, keyword: str) -> str:
        """Validate search keyword."""
        if not keyword or len(keyword.strip()) < 2:
            raise ValidationError("Keyword must be at least 2 characters")

        return keyword.strip()
