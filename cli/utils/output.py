"""Output utilities for Screen ASO."""

import json
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

from rich.console import Console


class OutputManager:
    """Manages output files and directories."""

    def __init__(self, base_dir: str = "outputs"):
        self.base_dir = Path(base_dir)
        self.console = Console()
        self._ensure_directories()

    def _ensure_directories(self) -> None:
        """Create output directories if they don't exist."""
        directories = ["searches", "scrapes", "analyses", "reports"]

        for directory in directories:
            (self.base_dir / directory).mkdir(parents=True, exist_ok=True)

    def get_timestamped_filename(self, prefix: str, extension: str = "json") -> str:
        """Generate a timestamped filename."""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        return f"{prefix}_{timestamp}.{extension}"

    def build_output_path(
        self,
        subdir: str,
        filename: str,
        *,
        store: Optional[str] = None,
        slug: Optional[str] = None,
        context: Optional[str] = None,
    ) -> Path:
        """Return a full output path following the folder convention."""
        output_dir = self._prepare_output_dir(
            subdir,
            store=store,
            slug=slug,
            context=context,
        )
        return output_dir / filename

    def save_json(
        self,
        data: Dict[str, Any],
        subdir: str,
        filename: str,
        *,
        app_slug: Optional[str] = None,
        store: Optional[str] = None,
        slug: Optional[str] = None,
        context: Optional[str] = None,
    ) -> Path:
        """Save data as JSON file (optionally inside an app-specific subdirectory)."""
        output_path = self.build_output_path(
            subdir,
            filename,
            store=store,
            slug=slug or app_slug,
            context=context,
        )

        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

        self.console.print(f"[green]✓[/green] Saved: {output_path}")
        return output_path

    def save_text(
        self,
        content: str,
        subdir: str,
        filename: str,
        *,
        app_slug: Optional[str] = None,
        store: Optional[str] = None,
        slug: Optional[str] = None,
        context: Optional[str] = None,
    ) -> Path:
        """Persist plain-text or Markdown content under outputs/ tree."""
        output_path = self.build_output_path(
            subdir,
            filename,
            store=store,
            slug=slug or app_slug,
            context=context,
        )

        with open(output_path, "w", encoding="utf-8") as handle:
            handle.write(content)

        self.console.print(f"[green]✓[/green] Saved: {output_path}")
        return output_path

    def load_json(self, filepath: str) -> Dict[str, Any]:
        """Load JSON file."""
        with open(filepath, "r", encoding="utf-8") as f:
            return json.load(f)

    def get_latest_file(self, subdir: str, pattern: str = "*.json") -> Path:
        """Get the most recent file in a subdirectory."""
        directory = self.base_dir / subdir
        files = list(directory.glob(pattern))

        if not files:
            raise FileNotFoundError(f"No files found in {directory}")

        return max(files, key=lambda f: f.stat().st_mtime)

    def print_summary(self, stats: Dict[str, Any]) -> None:
        """Print summary statistics."""
        from rich.table import Table

        table = Table(title="Summary", show_header=False)
        table.add_column("Metric", style="cyan")
        table.add_column("Value", style="green")

        for key, value in stats.items():
            table.add_row(key.replace("_", " ").title(), str(value))

        self.console.print(table)

    def derive_app_slug(
        self,
        *,
        app: Optional[Dict[str, Any]] = None,
        app_name: Optional[str] = None,
        app_id: Optional[str] = None,
        store: Optional[str] = None,
    ) -> str:
        """Return a filesystem-safe slug derived from app name/id and store label."""
        if app:
            app_name = app_name or app.get("app_name") or app.get("name") or app.get("title")
            app_id = app_id or app.get("app_id") or app.get("id")
            store = store or app.get("store")

        base_candidate = app_name or app_id or "app"
        base_slug = self._slugify(base_candidate)

        store_slug = self._normalize_store(store) or ""
        if store_slug:
            if not base_slug.endswith(store_slug):
                return f"{base_slug}-{store_slug}"
        return base_slug

    def derive_slug_from_payload(
        self,
        data: Dict[str, Any],
        default: str = "report",
    ) -> str:
        """Infer an app slug from a generic payload (app/app lists/results)."""
        app_entry = data.get("app")
        if isinstance(app_entry, dict):
            return self.derive_app_slug(app=app_entry)

        for key in ("apps", "results"):
            apps = data.get(key)
            if not isinstance(apps, list):
                continue
            for item in apps:
                candidate = item.get("app") if isinstance(item, dict) and isinstance(item.get("app"), dict) else item
                if isinstance(candidate, dict):
                    return self.derive_app_slug(app=candidate)

        return self._slugify(default)

    def infer_store_slug(
        self,
        *,
        app: Optional[Dict[str, Any]] = None,
        store: Optional[str] = None,
    ) -> Optional[str]:
        """Normalize a store identifier from explicit input or an app payload."""
        candidate_store = store
        if not candidate_store and app:
            for key in ("store", "source_store"):
                candidate_store = app.get(key)
                if candidate_store:
                    break

            if not candidate_store:
                raw_data = app.get("raw_data")
                if isinstance(raw_data, dict):
                    candidate_store = raw_data.get("store")

            if not candidate_store:
                app_id = app.get("app_id") or app.get("id")
                if app_id:
                    candidate_store = "app-store" if str(app_id).isdigit() else "play-store"

        return self._normalize_store(candidate_store)

    def _prepare_output_dir(
        self,
        subdir: str,
        *,
        store: Optional[str] = None,
        slug: Optional[str] = None,
        context: Optional[str] = None,
    ) -> Path:
        """Build and create the folder hierarchy for an output file."""
        store_segment = self._normalize_store(store)
        slug_segment = self._slugify(slug) if slug else None
        context_segment = self._slugify(context) if context else None

        output_dir = self.base_dir / subdir
        if store_segment:
            output_dir = output_dir / store_segment
        if slug_segment:
            output_dir = output_dir / slug_segment
        if context_segment:
            output_dir = output_dir / context_segment

        output_dir.mkdir(parents=True, exist_ok=True)
        return output_dir

    @staticmethod
    def _normalize_store(store: Optional[str]) -> Optional[str]:
        if not store:
            return None
        normalized = str(store).lower().replace("_", "-").strip()
        if not normalized:
            return None
        if "play" in normalized:
            return "play-store"
        if "app" in normalized:
            return "app-store"
        return OutputManager._slugify(normalized)

    @staticmethod
    def slugify(value: Optional[str]) -> str:
        """Public helper to normalize arbitrary labels for paths."""
        return OutputManager._slugify(value)

    @staticmethod
    def _slugify(value: Optional[str]) -> str:
        if not value:
            return "app"
        normalized = str(value).lower().strip()
        normalized = re.sub(r"[\s_]+", "-", normalized)
        normalized = re.sub(r"[^a-z0-9\-.]+", "-", normalized)
        normalized = re.sub(r"-{2,}", "-", normalized)
        normalized = normalized.strip("-.")
        return normalized or "app"
