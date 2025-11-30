"""Dear PyGui tabanlı masaüstü arayüzü."""
from __future__ import annotations

import json
import os
import queue
import subprocess
import sys
import threading
import time
import traceback
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, Optional

from matplotlib import font_manager
import dearpygui.dearpygui as dpg
from core import privacy

try:
    from pypdf import PdfReader
except Exception:
    PdfReader = None  # type: ignore

ROOT_DIR = Path(__file__).resolve().parents[1]
CLI_MODULE = "cli.main"
STORE_OPTIONS = ["app-store", "play-store"]
SORT_OPTIONS = ["most_relevant", "newest", "rating"]
FONT_NAMES = ["Arial", "Helvetica", "Georgia", "Trebuchet MS", "SF Pro", "DejaVu Sans"]
TURKISH_CHARS = "çğıöşüÇĞİÖŞÜ"
RESULT_ROOTS = [
    ROOT_DIR / "outputs",
    ROOT_DIR / "aso_results",
    ROOT_DIR / "app_store_search_results",
    ROOT_DIR / "play_store_search_results",
]
RESULT_EXTENSIONS = {".json": "json", ".pdf": "pdf", ".md": "md"}
MAX_HISTORY_ITEMS = 250
AI_RESULT_ROOT = ROOT_DIR / "outputs" / "ai_results"
AI_DEFAULT_ALLOWLIST = [
    "api.openai.com",
    "api.anthropic.com",
    "generativelanguage.googleapis.com",
    "openrouter.ai",
    "localhost",
    "127.0.0.1",
]
AI_PROVIDER_OPTIONS = ["Gemini", "OpenRouter"]
AI_GEMINI_MODELS = [
    "gemini-3-pro-preview",
    "gemini-2.5-pro",
    "gemini-2.5-flash",
    "gemini-2.5-flash-lite",
]
AI_OPENROUTER_MODELS = [
    "openai/gpt-5.1",
    "moonshotai/kimi-k2-thinking",
    "google/gemini-3-pro-preview",
    "anthropic/claude-sonnet-4.5",
    "x-ai/grok-4-fast",
]
AI_CUSTOM_MODEL_OPTION = "Custom model"
AI_MODEL_PRESETS = {"gemini": AI_GEMINI_MODELS, "openrouter": AI_OPENROUTER_MODELS}
AI_TASK_PRESETS = {
    "Review summary": "Read the app reviews and deliver a summary in max 8 bullets. Ignore any personal data.",
    "ASO keyword ideas": "Suggest 10-15 keywords relevant to the app; add a short rationale for each.",
    "Custom prompt": "",
}
AI_MAX_PREVIEW_CHARS = 3200
AI_LOG_MAX_CHARS = 9000


def _build_cli_command(args: list[str]) -> list[str]:
    """Resolve CLI command for both dev and frozen builds."""
    if getattr(sys, "frozen", False):
        exe_path = Path(sys.executable).resolve()
        candidates = [
            exe_path.parent / "aso-cli",  # alongside gui exe inside .app
            exe_path.with_name("aso-cli"),  # sibling in dist/ folder
        ]
        for candidate in candidates:
            if candidate.exists():
                return [str(candidate), *args]
    return [sys.executable, "-m", CLI_MODULE, *args]


@dataclass
class ResultEntry:
    path: Path
    kind: str
    modified: float
    size: int

    @property
    def label(self) -> str:
        timestamp = datetime.fromtimestamp(self.modified).strftime("%Y-%m-%d %H:%M")
        try:
            relative = self.path.relative_to(ROOT_DIR)
        except ValueError:
            relative = self.path
        return f"[{self.kind.upper()}] {relative} ({timestamp})"


def _format_size(num_bytes: int) -> str:
    step = 1024.0
    units = ["B", "KB", "MB", "GB"]
    size = float(num_bytes)
    for unit in units:
        if size < step:
            return f"{size:.1f} {unit}"
        size /= step
    return f"{size:.1f} TB"


def _collect_result_files(max_items: int = MAX_HISTORY_ITEMS) -> list[ResultEntry]:
    entries: list[ResultEntry] = []
    for root in RESULT_ROOTS:
        if not root.exists():
            continue
        for path in root.rglob("*"):
            if not path.is_file():
                continue
            suffix = path.suffix.lower()
            if suffix not in RESULT_EXTENSIONS:
                continue
            stat = path.stat()
            entries.append(
                ResultEntry(
                    path=path,
                    kind=RESULT_EXTENSIONS[suffix],
                    modified=stat.st_mtime,
                    size=stat.st_size,
                )
            )

    entries.sort(key=lambda item: item.modified, reverse=True)
    return entries[:max_items]


def _open_in_os(path: Path) -> tuple[bool, str | None]:
    try:
        if sys.platform == "darwin":
            subprocess.Popen(["open", str(path)])
        elif os.name == "nt":
            os.startfile(path)  # type: ignore[attr-defined]
        else:
            subprocess.Popen(["xdg-open", str(path)])
        return True, None
    except Exception as exc:  # noqa: BLE001
        return False, str(exc)


def _load_json_preview(path: Path, max_chars: int = 9000) -> str:
    try:
        raw_content = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        raw_content = path.read_text(errors="replace")

    try:
        parsed = json.loads(raw_content)
        pretty = json.dumps(parsed, ensure_ascii=False, indent=2)
    except Exception:
        pretty = raw_content

    if len(pretty) > max_chars:
        return pretty[:max_chars] + "\n... (output truncated)"
    return pretty


def _extract_pdf_preview(path: Path, max_chars: int = 1800) -> str:
    if PdfReader is None:
        return "pypdf is not installed. Run `pip install pypdf` to enable preview."

    try:
        reader = PdfReader(str(path))
        if not reader.pages:
            return "No PDF pages found."
        first_page = reader.pages[0]
        text = (first_page.extract_text() or "").strip()
    except Exception as exc:  # noqa: BLE001
        return f"PDF preview failed: {exc}"

    if not text:
        return "No text extracted. Open the file to view full content."

    if len(text) > max_chars:
        text = text[:max_chars] + "\n... (text truncated)"
    return text


def _slugify(value: str) -> str:
    cleaned = "".join(ch if ch.isalnum() or ch in "-._" else "-" for ch in value.lower())
    cleaned = cleaned.strip("-._")
    return cleaned or "ai_result"


def _truncate_text(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + "\n... (truncated)"


def _safe_read_text(path: Path, max_chars: Optional[int] = None) -> str:
    try:
        content = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        content = path.read_text(errors="replace")
    if max_chars is not None and len(content) > max_chars:
        return content[:max_chars]
    return content


def _load_result_preview(path: Path, max_chars: int = 2200) -> str:
    suffix = path.suffix.lower()
    if suffix == ".json":
        return _load_json_preview(path, max_chars=max_chars)
    if suffix == ".pdf":
        return _extract_pdf_preview(path, max_chars=max_chars)
    text = _safe_read_text(path, max_chars=max_chars * 2)
    if len(text) > max_chars:
        return text[:max_chars] + "\n... (output truncated)"
    return text


def _parse_allowlist(text: str) -> set[str]:
    hosts = [item.strip().lower() for item in text.split(",") if item.strip()]
    if not hosts:
        return set(AI_DEFAULT_ALLOWLIST)
    return set(hosts)


def _check_allowlist(url: str, allowlist: Iterable[str]) -> None:
    parsed = urllib.parse.urlparse(url)
    host = parsed.hostname or ""
    if host.lower() not in {h.lower() for h in allowlist}:
        raise ValueError(f"Host blocked by allowlist: {host}")


def _default_model(provider: str) -> str:
    provider_lower = provider.lower()
    if provider_lower == "gemini":
        return "gemini-2.5-flash"
    if provider_lower == "openrouter":
        return "gpt-4o-mini"
    return "gemini-2.5-flash"


def _load_and_redact_payload(path: Path, max_chars: int = AI_MAX_PREVIEW_CHARS) -> tuple[str, str]:
    """Return (sanitized_payload_text, preview_for_ui)."""
    suffix = path.suffix.lower()
    if suffix == ".json":
        raw_text = _safe_read_text(path, max_chars=max_chars * 4)
        try:
            parsed = json.loads(raw_text)
            sanitized = privacy.sanitize_reviews_for_output(parsed)
            pretty = json.dumps(sanitized, ensure_ascii=False, indent=2)
        except Exception:
            pretty = privacy.redact_text(raw_text)
        preview = _truncate_text(pretty, max_chars)
        return pretty, preview

    if suffix == ".pdf":
        preview_text = _extract_pdf_preview(path, max_chars=max_chars)
        redacted = privacy.redact_text(preview_text)
        return redacted, redacted

    raw_text = _safe_read_text(path, max_chars=max_chars * 2)
    redacted = privacy.redact_text(raw_text)
    return redacted, _truncate_text(redacted, max_chars)


def _is_app_store_id(app_id: str) -> bool:
    """Heuristic: numeric (optionally prefixed with 'id') IDs belong to App Store."""
    cleaned = app_id.strip().lower()
    if cleaned.startswith("id"):
        cleaned = cleaned[2:]
    return bool(cleaned) and cleaned.isdigit()


def _find_turkish_font_path() -> str | None:
    """Matplotlib yardımıyla Türkçe karakter destekli fontu bul."""
    try:
        font_path = font_manager.findfont("DejaVu Sans")
        font_file = Path(font_path)
        if font_file.exists():
            return str(font_file)
    except Exception:
        pass
    return None


def _create_modern_theme():
    with dpg.theme() as global_theme:
        with dpg.theme_component(dpg.mvAll):
            # Window & Background
            dpg.add_theme_color(dpg.mvThemeCol_WindowBg, (30, 30, 46))
            dpg.add_theme_color(dpg.mvThemeCol_ChildBg, (30, 30, 46))
            dpg.add_theme_color(dpg.mvThemeCol_PopupBg, (30, 30, 46))
            dpg.add_theme_color(dpg.mvThemeCol_Border, (69, 71, 90))
            dpg.add_theme_color(dpg.mvThemeCol_FrameBg, (49, 50, 68))
            dpg.add_theme_color(dpg.mvThemeCol_FrameBgHovered, (69, 71, 90))
            dpg.add_theme_color(dpg.mvThemeCol_FrameBgActive, (88, 91, 112))
            dpg.add_theme_color(dpg.mvThemeCol_TitleBg, (30, 30, 46))
            dpg.add_theme_color(dpg.mvThemeCol_TitleBgActive, (30, 30, 46))
            dpg.add_theme_color(dpg.mvThemeCol_MenuBarBg, (30, 30, 46))

            # Text
            dpg.add_theme_color(dpg.mvThemeCol_Text, (205, 214, 244))
            dpg.add_theme_color(dpg.mvThemeCol_TextDisabled, (108, 112, 134))

            # Buttons
            dpg.add_theme_color(dpg.mvThemeCol_Button, (137, 180, 250, 60))
            dpg.add_theme_color(dpg.mvThemeCol_ButtonHovered, (137, 180, 250, 100))
            dpg.add_theme_color(dpg.mvThemeCol_ButtonActive, (137, 180, 250, 150))

            # Tabs
            dpg.add_theme_color(dpg.mvThemeCol_Tab, (49, 50, 68))
            dpg.add_theme_color(dpg.mvThemeCol_TabHovered, (69, 71, 90))
            dpg.add_theme_color(dpg.mvThemeCol_TabActive, (137, 180, 250, 100))
            dpg.add_theme_color(dpg.mvThemeCol_TabUnfocused, (49, 50, 68))
            dpg.add_theme_color(dpg.mvThemeCol_TabUnfocusedActive, (88, 91, 112))

            # Header
            dpg.add_theme_color(dpg.mvThemeCol_Header, (69, 71, 90))
            dpg.add_theme_color(dpg.mvThemeCol_HeaderHovered, (88, 91, 112))
            dpg.add_theme_color(dpg.mvThemeCol_HeaderActive, (137, 180, 250, 100))

            # Styles
            dpg.add_theme_style(dpg.mvStyleVar_FrameRounding, 6)
            dpg.add_theme_style(dpg.mvStyleVar_WindowRounding, 8)
            dpg.add_theme_style(dpg.mvStyleVar_ChildRounding, 6)
            dpg.add_theme_style(dpg.mvStyleVar_PopupRounding, 6)
            dpg.add_theme_style(dpg.mvStyleVar_ScrollbarRounding, 6)
            dpg.add_theme_style(dpg.mvStyleVar_GrabRounding, 6)
            dpg.add_theme_style(dpg.mvStyleVar_TabRounding, 6)
            
            dpg.add_theme_style(dpg.mvStyleVar_ItemSpacing, 10, 10)
            dpg.add_theme_style(dpg.mvStyleVar_FramePadding, 10, 6)
            dpg.add_theme_style(dpg.mvStyleVar_CellPadding, 8, 4)

    return global_theme


def _ensure_turkish_font() -> int | str | None:
    """Cross-platform font yükle - çoklu işletim sistemi desteği."""
    platform_fonts = []
    
    # Platforma göre font yollarını belirle
    import platform
    system = platform.system()
    
    if system == "Darwin":  # macOS
        platform_fonts = [
            "/System/Library/Fonts/Supplemental/Arial.ttf",
            "/System/Library/Fonts/Supplemental/Georgia.ttf", 
            "/System/Library/Fonts/Supplemental/Trebuchet MS.ttf",
            "/System/Library/Fonts/Arial.ttf",
            "/System/Library/Fonts/Helvetica.ttf",
            "/Library/Fonts/Arial.ttf",
            "/Library/Fonts/Helvetica.ttf",
        ]
    elif system == "Windows":  # Windows
        platform_fonts = [
            "C:/Windows/Fonts/Arial.ttf",
            "C:/Windows/Fonts/calibri.ttf", 
            "C:/Windows/Fonts/Georgia.ttf",
            "C:/Windows/Fonts/tahoma.ttf",
            "C:/Windows/Fonts/verdana.ttf",
        ]
    elif system == "Linux":  # Linux
        platform_fonts = [
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
            "/usr/share/fonts/truetype/freefont/FreeSans.ttf",
            "/usr/share/fonts/opentype/noto/NotoSans-Regular.ttf",
            "/usr/share/fonts/TTF/arial.ttf",
        ]
    else:  # Diğer platformlar
        platform_fonts = []
    
    # Sistem fontlarını dene
    font_path = None
    for path in platform_fonts:
        if Path(path).exists():
            font_path = path
            break
    
    # Sistem fontu bulamazsa matplotlib'i kullan (fallback)
    if not font_path:
        font_path = _find_turkish_font_path()
    
    if not font_path:
        print(f"WARNING: No suitable font found on {system}")
        print("Using default system font - this may cause display issues")
        return None
        
    print(f"Font loaded: {Path(font_path).name} ({system})")
    
    header_font = None
    with dpg.font_registry():
        # Ana font (biraz daha küçük ve zarif)
        default_font = dpg.add_font(font_path, 16)
        dpg.add_font_range_hint(dpg.mvFontRangeHint_Default, parent=default_font)
        dpg.add_font_range_hint(dpg.mvFontRangeHint_Cyrillic, parent=default_font)
        
        # Başlık fontu (daha büyük)
        header_font = dpg.add_font(font_path, 22)
        dpg.add_font_range_hint(dpg.mvFontRangeHint_Default, parent=header_font)
        dpg.add_font_range_hint(dpg.mvFontRangeHint_Cyrillic, parent=header_font)
        
        # Türkçe karakterleri ekle
        for char in TURKISH_CHARS:
             dpg.add_font_chars([ord(char)], parent=default_font)
             dpg.add_font_chars([ord(char)], parent=header_font)

    dpg.bind_font(default_font)
    return header_font


class CLICommandRunner:
    def __init__(self, log_item: int, status_item: int, progress_item: int, main_status_item: int | str) -> None:
        self.log_item = log_item
        self.status_item = status_item
        self.progress_item = progress_item
        self.main_status_item = main_status_item
        self.queue: "queue.Queue[str]" = queue.Queue()
        self.thread: threading.Thread | None = None
        self.process: subprocess.Popen | None = None
        self.running = False
        self.current_task = ""
        self.log_buffer = ""
        self.progress_value = 0.0
        self.progress_overlay = "Ready"
        self.stage_patterns: list[tuple[str, float, str]] = [
            ("searching", 0.45, "Searching stores"),
            ("[init]", 0.55, "Starting Crawl4AI"),
            ("[fetch]", 0.65, "Downloading data"),
            ("[scrape]", 0.8, "Scraping pages"),
            ("[complete]", 0.95, "Finishing up"),
            ("saved:", 0.98, "Saving outputs"),
        ]
        self._last_complete_time = 0.0
        self._refresh_progress()

    def _set_progress(self, value: float, overlay: str) -> None:
        self.progress_value = max(0.0, min(1.0, value))
        self.progress_overlay = overlay
        if self.progress_value >= 1.0:
            self._last_complete_time = time.monotonic()
        
        # Update main status text
        if dpg.does_item_exist(self.main_status_item):
            dpg.set_value(self.main_status_item, overlay)

    def _refresh_progress(self) -> None:
        dpg.set_value(self.progress_item, self.progress_value)
        dpg.configure_item(self.progress_item, overlay=self.progress_overlay)

    def start(self, description: str, args: list[str]) -> None:
        if self.running:
            self.queue.put("\nWARNING: Cannot run new command while previous task is still running.\n")
            return

        self.current_task = description
        self.running = True
        dpg.set_value(self.status_item, f"{description} running...")
        self.queue.put(f"\n► {description} starting...\n")
        self.queue.put(f"Komut: {' '.join(args)}\n")
        self.queue.put("-" * 50 + "\n")
        self._set_progress(0.2, f"{description} starting...")
        self._refresh_progress()
        
        self.thread = threading.Thread(
            target=self._run_command, args=(args, description), daemon=True
        )
        self.thread.start()

    def _run_command(self, args: list[str], description: str) -> None:
        command = _build_cli_command(args)
        try:
            self.process = subprocess.Popen(
                command,
                cwd=ROOT_DIR,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
            )

            if self.process.stdout:
                for line in self.process.stdout:
                    if line.strip():  # Boş satırları atla
                        self.queue.put(line)

            return_code = self.process.wait()
            if return_code == 0:
                self.queue.put(f"\n✅ {description} completed successfully.\n")
                self._set_progress(1.0, f"{description} completed.")
            else:
                self.queue.put(f"\n❌ {description} failed with exit code {return_code}.\n")
                self._set_progress(1.0, f"{description} failed.")
        except Exception as exc:
            self.queue.put(f"\n❌ Critical error: {exc}\n")
            self._set_progress(1.0, "Critical error")
        finally:
            self.running = False
            self.process = None

    def stop(self) -> None:
        if self.process and self.running:
            try:
                self.process.terminate()
                self.queue.put(f"\n⏹️ {self.current_task} stopped.\n")
                self.running = False
                self.process = None
                self._set_progress(0.0, f"{self.current_task} stopped")
                self._refresh_progress()
            except Exception as e:
                self.queue.put(f"\n❌ Durdurma hatası: {e}\n")

    def poll(self) -> None:
        updated = False
        while not self.queue.empty():
            chunk = self.queue.get()
            self._update_stage_from_chunk(chunk)
            self.log_buffer += chunk
            updated = True
        if updated:
            dpg.set_value(self.log_item, self.log_buffer)
        
        self._refresh_progress()

        # Durum göstergesini güncelle
        if self.running:
            dpg.set_value(self.status_item, f"{self.current_task} running...")
        else:
            dpg.set_value(self.status_item, "Ready")

        if not self.running and self.progress_value >= 1.0:
            if time.monotonic() - self._last_complete_time > 0.6:
                self._set_progress(0.0, "Ready")
                self._refresh_progress()

    def clear_log(self) -> None:
        self.log_buffer = "> Log cleared.\n"
        dpg.set_value(self.log_item, self.log_buffer)

    def _update_stage_from_chunk(self, chunk: str) -> None:
        content = chunk.lower()
        for keyword, target, overlay in self.stage_patterns:
            if keyword in content and self.progress_value < target:
                self._set_progress(target, overlay)
                self._refresh_progress()
                break


class ResultHistoryPanel:
    def __init__(self) -> None:
        self.items: list[ResultEntry] = []
        self.filtered_items: list[ResultEntry] = []
        self.current: ResultEntry | None = None
        self.list_tag = "result_history_list"
        self.preview_tag = "result_preview_text"
        self.meta_tag = "result_meta_text"
        self.status_tag = "result_status_text"
        self.filter_tag = "result_filter_combo"
        self.open_button_tag = "result_open_button"
        self.copy_button_tag = "result_copy_button"

    def build_tab(self) -> None:
        with dpg.tab(label="Results & History"):
            dpg.add_spacer(height=10)
            with dpg.group(horizontal=True):
                dpg.add_spacer(width=10)
                with dpg.group():
                    dpg.add_text("Result History", color=(137, 180, 250))
                    dpg.add_spacer(height=10)
                    with dpg.group(horizontal=True):
                        dpg.add_text("Type filter")
                        dpg.add_combo(
                            ["All", "PDF", "JSON+MD"],
                            default_value="All",
                            width=120,
                            tag=self.filter_tag,
                            callback=self._on_filter_change,
                        )
                        dpg.add_button(label="Refresh", width=100, callback=self._refresh)
                        dpg.add_button(
                            label="Open file",
                            width=110,
                            tag=self.open_button_tag,
                            callback=self._open_current,
                            enabled=False,
                        )
                        dpg.add_button(
                            label="Copy path",
                            width=120,
                            tag=self.copy_button_tag,
                            callback=self._copy_path,
                            enabled=False,
                        )

                    dpg.add_spacer(height=5)
                    with dpg.group(horizontal=True):
                        self.list_tag = dpg.add_listbox(
                            items=[],
                            num_items=12,
                            width=-1,
                            callback=self._on_select,
                        )
                    dpg.add_spacer(height=5)
                    with dpg.group():
                        self.status_tag = dpg.add_text("No selection yet", color=(108, 112, 134))
                        self.meta_tag = dpg.add_text("", wrap=600)
                        dpg.add_spacer(height=6)
                        dpg.add_text("Preview (JSON/Markdown/PDF)", color=(166, 173, 200))
                        self.preview_tag = dpg.add_input_text(
                            multiline=True,
                            readonly=True,
                            height=300,
                            width=-1,
                            default_value="Select a result to preview.",
                        )

            self._refresh()

    def _refresh(self, sender: int | None = None, app_data: Any | None = None, user_data: Any | None = None) -> None:
        self.items = _collect_result_files()
        self._apply_filter()

    def _apply_filter(self) -> None:
        filter_value = dpg.get_value(self.filter_tag) if dpg.does_item_exist(self.filter_tag) else "All"
        filter_kind = None
        if filter_value == "PDF":
            filter_kind = "pdf"
        elif filter_value == "JSON+MD":
            filter_kind = {"json", "md"}

        if filter_kind is None:
            self.filtered_items = list(self.items)
        elif isinstance(filter_kind, set):
            self.filtered_items = [item for item in self.items if item.kind in filter_kind]
        else:
            self.filtered_items = [item for item in self.items if item.kind == filter_kind]

        labels = [item.label for item in self.filtered_items]
        dpg.configure_item(self.list_tag, items=labels)

        self.current = None
        dpg.set_value(self.preview_tag, "Select a result to preview.")
        dpg.set_value(self.meta_tag, "")
        dpg.configure_item(self.open_button_tag, enabled=False)
        dpg.configure_item(self.copy_button_tag, enabled=False)

        if labels:
            dpg.set_value(self.status_tag, f"{len(labels)} result(s) listed")
        else:
            dpg.set_value(self.status_tag, "No records found")

    def _on_filter_change(self, sender: int, app_data: Any) -> None:
        self._apply_filter()

    def _on_select(self, sender: int, app_data: Any) -> None:
        label = str(app_data)
        entry = next((item for item in self.filtered_items if item.label == label), None)
        if not entry:
            return

        self.current = entry
        dpg.configure_item(self.open_button_tag, enabled=True)
        dpg.configure_item(self.copy_button_tag, enabled=True)

        human_time = datetime.fromtimestamp(entry.modified).strftime("%Y-%m-%d %H:%M:%S")
        parts = [
            f"File: {entry.path.relative_to(ROOT_DIR)}",
            f"Type: {entry.kind.upper()}",
            f"Size: {_format_size(entry.size)}",
            f"Time: {human_time}",
        ]
        dpg.set_value(self.meta_tag, " | ".join(parts))
        dpg.set_value(self.status_tag, f"{entry.kind.upper()} selected")

        preview = _load_result_preview(entry.path)
        dpg.set_value(self.preview_tag, preview)

    def _open_current(self, sender: int, app_data: Any) -> None:
        if not self.current:
            return
        success, error = _open_in_os(self.current.path)
        if success:
            dpg.set_value(self.status_tag, "Opening in file system...")
        elif error:
            dpg.set_value(self.status_tag, f"Cannot open file: {error}")

    def _copy_path(self, sender: int, app_data: Any) -> None:
        if not self.current:
            return
        dpg.set_clipboard_text(str(self.current.path))
        dpg.set_value(self.status_tag, "File path copied to clipboard")

    def resize(self, width: int, height: int) -> None:
        """Resize panel components based on window dimensions."""
        list_width = max(300, width - 60)
        preview_height = max(150, height - 280)
        num_items = max(6, min(16, (height - 200) // 22))
        
        if dpg.does_item_exist(self.list_tag):
            dpg.configure_item(self.list_tag, width=list_width, num_items=num_items)
        if dpg.does_item_exist(self.preview_tag):
            dpg.configure_item(self.preview_tag, width=list_width, height=preview_height)
        if dpg.does_item_exist(self.meta_tag):
            dpg.configure_item(self.meta_tag, wrap=max(320, min(700, list_width)))


@dataclass
class AITaskRequest:
    input_path: Path
    task: str
    provider: str
    model: str
    max_tokens: int
    temperature: float
    max_budget: float
    allowlist: set[str]
    custom_prompt: str
    api_key: str
    base_url: Optional[str] = None

    def __post_init__(self) -> None:
        if not self.allowlist:
            raise ValueError("Allowlist cannot be empty.")


@dataclass
class AIRunResult:
    output_text: str
    saved_path: Path
    status: str


class AIAssistPanel:
    def __init__(self, header_font: int | str | None = None) -> None:
        self.header_font = header_font
        self.input_path_tag = "ai_input_path"
        self.file_dialog_tag = "ai_file_dialog"
        self.recent_list_tag = "ai_recent_list"
        self.task_tag = "ai_task_combo"
        self.custom_prompt_tag = "ai_custom_prompt"
        self.provider_tag = "ai_provider_combo"
        self.model_preset_tag = "ai_model_preset"
        self.model_tag = "ai_model_input"
        self.key_tag = "ai_key_input"
        self.base_url_tag = "ai_base_url_input"
        self.max_tokens_tag = "ai_max_tokens"
        self.temperature_tag = "ai_temperature"
        self.allowlist_tag = "ai_allowlist_input"
        self.status_tag = "ai_status_text"
        self.log_tag = "ai_log_output"
        self.progress_tag = "ai_progress_bar"
        self.history_list_tag = "ai_history_list"
        self.history_meta_tag = "ai_history_meta"
        self.saved_path_tag = "ai_saved_path"
        self._log_buffer = "> AI Assist ready.\n"
        self._current_saved: Path | None = None
        self._running = False
        self._thread: threading.Thread | None = None
        self._queue: "queue.Queue[str]" = queue.Queue()
        self._result_queue: "queue.Queue[AIRunResult]" = queue.Queue()
        self._progress_value = 0.0
        self._progress_overlay = "Ready"
        self._last_complete_time = 0.0
        self._history_paths: dict[str, Path] = {}  # Label -> Path mapping

    def _append_log(self, text: str, ensure_space: int | None = None) -> None:
        if ensure_space is None:
            ensure_space = len(text)
        if ensure_space > 0 and len(self._log_buffer) + ensure_space > AI_LOG_MAX_CHARS:
            keep = max(0, AI_LOG_MAX_CHARS - ensure_space)
            self._log_buffer = self._log_buffer[-keep:]
        self._log_buffer += text
        if dpg.does_item_exist(self.log_tag):
            dpg.set_value(self.log_tag, self._log_buffer[-AI_LOG_MAX_CHARS:])

    def build_tab(self) -> None:
        default_provider = AI_PROVIDER_OPTIONS[0]
        default_model = _default_model(default_provider)

        def add_header(text: str) -> int:
            header_item = dpg.add_text(text, color=(137, 180, 250))
            if self.header_font:
                dpg.bind_item_font(header_item, self.header_font)
            return header_item

        with dpg.file_dialog(
            show=False,
            callback=self._on_file_selected,
            tag=self.file_dialog_tag,
            width=650,
            height=420,
            default_path=str(ROOT_DIR),
        ):
            dpg.add_file_extension("JSON (*.json){.json,.JSON}")
            dpg.add_file_extension("PDF (*.pdf){.pdf,.PDF}")
            dpg.add_file_extension("Markdown (*.md){.md,.MD}")
            dpg.add_file_extension("All Files (*.*){.*}")

        with dpg.tab(label="AI Assist"):
            dpg.add_spacer(height=10)
            add_header("AI Assist")
            dpg.add_text("Run AI over redacted analysis outputs.", color=(166, 173, 200))
            dpg.add_spacer(height=10)

            with dpg.group(horizontal=True):
                # Sol panel (tag eklendi)
                with dpg.child_window(width=520, height=-1, horizontal_scrollbar=False, tag="ai_left_panel"):
                    # 1. File & Data Section
                    dpg.add_text("1. Data Source", color=(137, 180, 250))
                    dpg.add_separator()
                    dpg.add_spacer(height=4)
                    
                    self.input_path_tag = dpg.add_input_text(
                        hint="Example: outputs/analyses/aso_app.json",
                        width=-1,
                    )
                    with dpg.group(horizontal=True):
                        dpg.add_button(label="Pick file", width=100, callback=self._open_file_dialog)
                        dpg.add_button(label="Refresh recent", width=100, callback=self._refresh_recent)
                        dpg.add_button(label="Validate", width=-1, callback=self._refresh_preview)
                    
                    dpg.add_spacer(height=4)
                    self.recent_list_tag = dpg.add_listbox(
                        items=[],
                        num_items=4,
                        width=-1,
                        callback=self._on_recent_select,
                    )
                    dpg.add_spacer(height=10)

                    # 2. Task & Model Section
                    dpg.add_text("2. Task & Model", color=(137, 180, 250))
                    dpg.add_separator()
                    dpg.add_spacer(height=4)
                    
                    with dpg.group(horizontal=True):
                        dpg.add_text("Task:", color=(166, 173, 200))
                        self.task_tag = dpg.add_combo(
                            list(AI_TASK_PRESETS.keys()),
                            default_value="Review summary",
                            width=-1,
                            callback=self._on_task_change,
                        )
                    
                    self.custom_prompt_tag = dpg.add_input_text(
                        multiline=True,
                        hint="Custom prompt (only when task=Custom prompt)",
                        height=60,
                        width=-1,
                        show=False,
                    )
                    dpg.add_spacer(height=4)
                    
                    with dpg.group(horizontal=True):
                        self.provider_tag = dpg.add_combo(
                            AI_PROVIDER_OPTIONS,
                            default_value=default_provider,
                            width=120,
                            callback=self._on_provider_change,
                        )
                        self.model_preset_tag = dpg.add_combo(
                            AI_GEMINI_MODELS + [AI_CUSTOM_MODEL_OPTION],
                            default_value=default_model if default_model in AI_GEMINI_MODELS else AI_CUSTOM_MODEL_OPTION,
                            width=200,
                            callback=self._on_model_preset_change,
                        )
                        self.model_tag = dpg.add_input_text(
                            default_value=default_model,
                            width=-1,
                            hint="Model name (custom allowed)",
                            callback=self._on_model_change,
                        )
                    
                    self.key_tag = dpg.add_input_text(
                        hint="API key (not logged)",
                        password=True,
                        width=-1,
                    )
                    self.base_url_tag = dpg.add_input_text(
                        default_value="https://openrouter.ai/api/v1",
                        width=-1,
                        hint="OpenRouter base URL",
                    )
                    self._apply_provider_state(default_provider)
                    dpg.add_spacer(height=10)

                    # 3. Action Section
                    dpg.add_button(label="RUN AI ANALYSIS", width=-1, height=32, callback=self._run_task)
                    dpg.add_spacer(height=10)

                    # 4. Advanced Settings (Collapsible for cleaner look, or just open)
                    with dpg.collapsing_header(label="Advanced Settings", default_open=False):
                        dpg.add_text("Limits & Safety", color=(166, 173, 200))
                        with dpg.group(horizontal=True):
                            dpg.add_text("Tokens:")
                            self.max_tokens_tag = dpg.add_slider_int(
                                default_value=4096,
                                min_value=50,
                                max_value=4096,
                                width=-1,
                            )
                        
                        with dpg.group(horizontal=True):
                            dpg.add_text("Temp:  ")
                            self.temperature_tag = dpg.add_slider_float(
                                default_value=0.40,
                                min_value=0.0,
                                max_value=1.0,
                                width=-1,
                                format="%.2f",
                            )
                        
                        dpg.add_spacer(height=4)
                        dpg.add_text("Allowlist:")
                        self.allowlist_tag = dpg.add_input_text(
                            default_value=",".join(AI_DEFAULT_ALLOWLIST),
                            width=-1,
                            hint="Host allowlist (comma-separated)",
                            multiline=True,
                            height=50,
                        )
                        dpg.add_button(label="Clear API Key", width=-1, callback=self._clear_key)
                    
                    dpg.add_spacer(height=4)
                    self.status_tag = dpg.add_text("Ready", color=(166, 227, 161))

                dpg.add_spacer(width=10)

                dpg.add_spacer(width=10)

                # Right panel (tag added)
                with dpg.child_window(width=-1, height=-1, horizontal_scrollbar=False, tag="ai_right_panel"):
                    dpg.add_text("Progress", color=(166, 173, 200))
                    self.progress_tag = dpg.add_progress_bar(
                        default_value=0.0,
                        overlay="Ready",
                        height=16,
                        width=-1,
                    )
                    dpg.add_spacer(height=6)
                    dpg.add_text("AI Log", color=(166, 173, 200))
                    self.log_tag = dpg.add_input_text(
                        multiline=True,
                        readonly=True,
                        height=150,
                        width=-1,
                        default_value=self._log_buffer,
                    )
                    dpg.add_spacer(height=6)
                    dpg.add_text("AI Results", color=(166, 173, 200))
                    self.history_list_tag = dpg.add_listbox(
                        items=[],
                        num_items=6,
                        width=-1,
                        callback=self._on_history_select,
                    )
                    self.history_meta_tag = dpg.add_text("", wrap=600)
                    self.saved_path_tag = dpg.add_text("", wrap=600, color=(137, 180, 250))

            self._refresh_recent()
            self._refresh_history()

    def poll(self) -> None:
        while not self._queue.empty():
            chunk = self._queue.get()
            self._append_log(chunk)

        if not self._running and self._progress_value >= 1.0:
            if time.monotonic() - self._last_complete_time > 0.5:
                self._set_progress(0.0, "Ready")

        while not self._result_queue.empty():
            result = self._result_queue.get()
            dpg.set_value(self.status_tag, result.status)
            self._current_saved = result.saved_path
            try:
                saved_rel = result.saved_path.relative_to(ROOT_DIR)
            except ValueError:
                saved_rel = result.saved_path
            saved_text = f"Saved: {saved_rel}"
            dpg.set_value(self.saved_path_tag, saved_text)
            preview = _truncate_text(result.output_text, 3200)
            log_block = f"\n✔️ {saved_text}\n\n--- AI Output ---\n{preview}\n------------------\n"
            self._append_log(log_block, ensure_space=len(log_block))
            self._refresh_history()

        self._refresh_progress()

    def _set_progress(self, value: float, overlay: str) -> None:
        self._progress_value = max(0.0, min(1.0, value))
        self._progress_overlay = overlay
        if self._progress_value >= 1.0:
            self._last_complete_time = time.monotonic()

    def _refresh_progress(self) -> None:
        if dpg.does_item_exist(self.progress_tag):
            dpg.set_value(self.progress_tag, self._progress_value)
            dpg.configure_item(self.progress_tag, overlay=self._progress_overlay)

    def _refresh_recent(self, sender: int | None = None, app_data: Any | None = None, user_data: Any | None = None) -> None:
        entries = _collect_result_files(max_items=40)
        items = []
        for entry in entries:
            try:
                label = str(entry.path.relative_to(ROOT_DIR))
            except ValueError:
                label = str(entry.path)
            items.append(label)
        dpg.configure_item(self.recent_list_tag, items=items)

    def _refresh_preview(self, sender: int | None = None, app_data: Any | None = None, user_data: Any | None = None) -> None:
        path_value = dpg.get_value(self.input_path_tag).strip()
        if not path_value:
            dpg.set_value(self.status_tag, "File path is empty.")
            return
        path = (ROOT_DIR / path_value).resolve() if not Path(path_value).is_absolute() else Path(path_value)
        if not path.exists():
            dpg.set_value(self.status_tag, "File not found.")
            return
        try:
            _load_and_redact_payload(path)
            dpg.set_value(self.status_tag, "File validated, ready to run.")
            self._append_log(f"\nPreview validated: {path.name}\n")
        except Exception as exc:  # noqa: BLE001
            message = f"Preview error: {exc}"
            dpg.set_value(self.status_tag, message)
            self._append_log("\n" + message + "\n")

    def _open_file_dialog(self, sender: int, app_data: Any) -> None:
        if self.file_dialog_tag and dpg.does_item_exist(self.file_dialog_tag):
            dpg.show_item(self.file_dialog_tag)

    def _on_file_selected(self, sender: int, app_data: Any) -> None:
        file_path_name = app_data.get("file_path_name") if isinstance(app_data, dict) else None
        if not file_path_name:
            return
        path = Path(file_path_name)
        try:
            relative = path.relative_to(ROOT_DIR)
            value = str(relative)
        except ValueError:
            value = str(path)
        dpg.set_value(self.input_path_tag, value)
        self._refresh_preview()

    def _on_task_change(self, sender: int, app_data: Any) -> None:
        task = str(app_data)
        dpg.configure_item(self.custom_prompt_tag, show=(task == "Custom prompt"))

    def _apply_provider_state(self, provider: str) -> None:
        is_openrouter = provider.lower() == "openrouter"
        if dpg.does_item_exist(self.base_url_tag):
            dpg.configure_item(self.base_url_tag, enabled=is_openrouter, show=is_openrouter)
            if is_openrouter:
                current_base = dpg.get_value(self.base_url_tag)
                if not current_base:
                    dpg.set_value(self.base_url_tag, "https://openrouter.ai/api/v1")
        self._sync_model_presets(provider)

    def _on_provider_change(self, sender: int, app_data: Any) -> None:
        provider = str(app_data)
        default_model = _default_model(provider)
        dpg.set_value(self.model_tag, default_model)
        self._apply_provider_state(provider)

    def _on_model_preset_change(self, sender: int, app_data: Any) -> None:
        selection = str(app_data)
        if not selection or selection == AI_CUSTOM_MODEL_OPTION:
            return
        dpg.set_value(self.model_tag, selection)

    def _on_model_change(self, sender: int, app_data: Any) -> None:
        provider = str(dpg.get_value(self.provider_tag) or "")
        model_value = str(app_data) if app_data is not None else None
        self._sync_model_presets(provider, model_value)

    def _sync_model_presets(self, provider: str, model_value: str | None = None) -> None:
        if not dpg.does_item_exist(self.model_preset_tag):
            return
        presets = AI_MODEL_PRESETS.get(provider.lower())
        show_presets = bool(presets)
        dpg.configure_item(self.model_preset_tag, show=show_presets, enabled=show_presets)
        if not show_presets:
            dpg.set_value(self.model_preset_tag, "")
            return
        options = list(presets) + [AI_CUSTOM_MODEL_OPTION]
        dpg.configure_item(self.model_preset_tag, items=options)
        active_model = (model_value or dpg.get_value(self.model_tag) or "").strip()
        selection = active_model if active_model in presets else AI_CUSTOM_MODEL_OPTION
        dpg.set_value(self.model_preset_tag, selection)

    def _clear_key(self, sender: int, app_data: Any) -> None:
        dpg.set_value(self.key_tag, "")
        dpg.set_value(self.status_tag, "Key cleared")

    def _on_recent_select(self, sender: int, app_data: Any) -> None:
        selection = str(app_data)
        if not selection:
            return
        dpg.set_value(self.input_path_tag, selection)
        self._refresh_preview()

    def _on_history_select(self, sender: int, app_data: Any) -> None:
        selection = str(app_data)
        if not selection:
            return
        
        # Kısaltılmış label'dan gerçek path'i al
        path = self._history_paths.get(selection)
        if not path:
            # Fallback: Eski yöntemle dene
            if not Path(selection).is_absolute():
                path = ROOT_DIR / selection
            else:
                path = Path(selection)
        
        if not path or not path.exists():
            dpg.set_value(self.history_meta_tag, "Record not found.")
            return
        
        content = _load_result_preview(path, max_chars=2400)
        human_time = datetime.fromtimestamp(path.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S")
        try:
            relative_path = path.relative_to(ROOT_DIR)
        except ValueError:
            relative_path = path
        dpg.set_value(self.history_meta_tag, f"{path.name} | {human_time}")
        dpg.set_value(self.saved_path_tag, f"Selected: {relative_path}")
        preview = _truncate_text(content, 3200)
        log_block = (
            f"\nSelected entry: {relative_path}\n--- AI Output (history) ---\n{preview}\n---------------------------\n"
        )
        self._append_log(log_block, ensure_space=len(log_block))

    def _run_task(self, sender: int, app_data: Any) -> None:
        if self._running:
            dpg.set_value(self.status_tag, "Already running...")
            return
        request = self._build_request()
        if request is None:
            return
        self._append_log("\n► Starting AI task...\n")
        self._set_progress(0.2, "Preparing")
        self._running = True
        self._thread = threading.Thread(target=self._worker, args=(request,), daemon=True)
        self._thread.start()

    def _build_request(self) -> AITaskRequest | None:
        path_value = dpg.get_value(self.input_path_tag).strip()
        if not path_value:
            dpg.set_value(self.status_tag, "File path is required")
            return None
        path = (ROOT_DIR / path_value).resolve() if not Path(path_value).is_absolute() else Path(path_value)
        if not path.exists():
            dpg.set_value(self.status_tag, "File not found")
            return None
        task = dpg.get_value(self.task_tag)
        provider = dpg.get_value(self.provider_tag)
        model = dpg.get_value(self.model_tag).strip() or _default_model(provider)
        api_key = dpg.get_value(self.key_tag).strip()
        if provider in {"Gemini", "OpenRouter"} and not api_key:
            dpg.set_value(self.status_tag, "API key required")
            return None
        max_tokens = int(dpg.get_value(self.max_tokens_tag) or 400)
        temperature = float(dpg.get_value(self.temperature_tag) or 0.2)
        allowlist = _parse_allowlist(dpg.get_value(self.allowlist_tag))
        custom_prompt = dpg.get_value(self.custom_prompt_tag) if task == "Custom prompt" else ""
        base_url = dpg.get_value(self.base_url_tag) if provider == "OpenRouter" else None
        try:
            return AITaskRequest(
                input_path=path,
                task=task,
                provider=provider,
                model=model,
                max_tokens=max_tokens,
                temperature=temperature,
                max_budget=0.0,
                allowlist=allowlist,
                custom_prompt=custom_prompt or "",
                api_key=api_key,
                base_url=base_url,
            )
        except ValueError as exc:
            dpg.set_value(self.status_tag, str(exc))
            return None

    def _worker(self, request: AITaskRequest) -> None:
        try:
            self._queue.put("Applying redaction...\n")
            payload_text, _preview = _load_and_redact_payload(request.input_path)
            limited_payload = _truncate_text(payload_text, 5000)
            prompt = self._build_prompt(request, limited_payload)
            self._queue.put("Checking allowlist...\n")

            output_text = self._call_provider(request, prompt)
            self._queue.put("Saving result...\n")
            saved_path = self._save_output(request, output_text)
            self._set_progress(1.0, "Done")
            self._queue.put("✅ Done.\n")
            self._result_queue.put(
                AIRunResult(
                    output_text=output_text,
                    saved_path=saved_path,
                    status="Done",
                )
            )
        except Exception as exc:  # noqa: BLE001
            self._set_progress(1.0, "Error")
            msg = f"Error: {exc}"
            self._queue.put(msg + "\n")
            self._result_queue.put(
                AIRunResult(
                    output_text=msg,
                    saved_path=request.input_path,
                    status="Error",
                )
            )
        finally:
            self._running = False

    def _build_prompt(self, request: AITaskRequest, payload_text: str) -> str:
        base_instruction = AI_TASK_PRESETS.get(request.task, "")
        if request.task == "Custom prompt":
            base_instruction = request.custom_prompt or "Summarize the provided text."
        if not base_instruction:
            base_instruction = "Summarize the provided text."

        system_guard = (
            "Use only the provided redacted text. Do not invent or fetch external data. "
            "Respond in English with concise, actionable output."
        )
        parts = [
            system_guard,
            f"Task: {base_instruction}",
            "Data (redacted):",
            payload_text,
        ]
        return "\n\n".join(parts)

    def _call_provider(self, request: AITaskRequest, prompt: str) -> str:
        provider = request.provider.lower()
        if provider == "gemini":
            return self._call_gemini(request, prompt)
        if provider == "openrouter":
            return self._call_openrouter(request, prompt)
        raise RuntimeError(f"Unknown provider: {request.provider}")

    def _call_gemini(self, request: AITaskRequest, prompt: str) -> str:
        model = request.model or _default_model("gemini")
        url = (
            f"https://generativelanguage.googleapis.com/v1beta/models/"
            f"{model}:generateContent?key={urllib.parse.quote(request.api_key)}"
        )
        _check_allowlist(url, request.allowlist)
        body = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {
                "maxOutputTokens": max(50, request.max_tokens),
                "temperature": max(0.0, min(1.0, request.temperature)),
                "responseMimeType": "text/plain",
            },
        }
        data = json.dumps(body).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=data,
            headers={"Content-Type": "application/json", "x-goog-api-key": request.api_key},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                payload = resp.read()
                parsed = json.loads(payload)
        except urllib.error.HTTPError as exc:
            raise RuntimeError(f"Gemini HTTP error: {exc.code}") from exc
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(f"Gemini call failed: {exc}") from exc

        candidates = parsed.get("candidates") if isinstance(parsed, dict) else None
        if not candidates:
            return "No response received."
        first = candidates[0]
        content = first.get("content", {}) if isinstance(first, dict) else {}
        parts = content.get("parts") if isinstance(content, dict) else None
        texts: list[str] = []
        if isinstance(parts, list):
            for part in parts:
                if isinstance(part, dict):
                    text_value = part.get("text")
                    if isinstance(text_value, str):
                        texts.append(text_value)
        if texts:
            return "\n".join(texts).strip()
        finish_reason = first.get("finishReason") if isinstance(first, dict) else None
        fallback = json.dumps(parsed, ensure_ascii=False)
        return (
            f"Empty response (finishReason={finish_reason or 'unknown'}). "
            f"Increase max tokens or shorten the prompt.\nRaw response: {fallback}"
        )

    def _call_openrouter(self, request: AITaskRequest, prompt: str) -> str:
        base_url = request.base_url or "https://openrouter.ai/api/v1"
        url = base_url.rstrip("/") + "/chat/completions"
        _check_allowlist(url, request.allowlist)
        body = {
            "model": request.model,
            "messages": [
                {
                    "role": "system",
                    "content": "Use only the provided redacted data; do not generate personal data. Respond in English.",
                },
                {"role": "user", "content": prompt},
            ],
            "max_tokens": max(50, request.max_tokens),
            "temperature": max(0.0, min(1.0, request.temperature)),
        }
        data = json.dumps(body).encode("utf-8")
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {request.api_key}",
            "HTTP-Referer": "https://screenaso.local",
            "X-Title": "Screen ASO Desktop",
        }
        req = urllib.request.Request(url, data=data, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                payload = resp.read()
                parsed = json.loads(payload)
        except urllib.error.HTTPError as exc:
            raise RuntimeError(f"OpenRouter HTTP error: {exc.code}") from exc
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(f"OpenRouter call failed: {exc}") from exc

        choices = parsed.get("choices") if isinstance(parsed, dict) else None
        if choices and isinstance(choices, list):
            msg = choices[0].get("message") if isinstance(choices[0], dict) else None
            if msg and isinstance(msg, dict):
                content = msg.get("content")
                if isinstance(content, str):
                    return content.strip()
        return json.dumps(parsed, ensure_ascii=False)

    def _save_output(self, request: AITaskRequest, output_text: str) -> Path:
        slug = _slugify(request.input_path.stem)
        target_dir = AI_RESULT_ROOT / slug
        target_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"ai_{ts}.md"
        allowlist_text = ", ".join(sorted(request.allowlist)) if request.allowlist else "None"
        body_lines = [
            "# AI Assist Result",
            "",
            "## Summary",
            f"- Provider: {request.provider}",
            f"- Model: {request.model}",
            f"- Task: {request.task}",
            f"- Allowlist: {allowlist_text}",
            f"- Input: {request.input_path}",
            f"- Time: {ts}",
            "",
            "## Output",
            "",
            "```",
            output_text.strip() or "No output produced.",
            "```",
            "",
        ]
        content = "\n".join(body_lines)
        path = target_dir / filename
        path.write_text(content, encoding="utf-8")
        return path

    def _refresh_history(self) -> None:
        if not AI_RESULT_ROOT.exists():
            AI_RESULT_ROOT.mkdir(parents=True, exist_ok=True)
        self._history_paths = {}  # Label -> Path mapping
        items = []
        paths = [
            path
            for path in AI_RESULT_ROOT.rglob("ai_*")
            if path.is_file() and path.suffix.lower() in {".json", ".md"}
        ]
        for path in sorted(paths, key=lambda p: p.stat().st_mtime, reverse=True):
            try:
                relative_path = path.relative_to(ROOT_DIR)
                # Path'i kısalt - sadece son 2 dizin + dosya adı
                parts = relative_path.parts
                if len(parts) > 3:
                    label = ".../" + "/".join(parts[-2:])
                else:
                    label = str(relative_path)
            except ValueError:
                label = path.name  # Sadece dosya adı
            items.append(label)
            self._history_paths[label] = path  # Mapping kaydet
        dpg.configure_item(self.history_list_tag, items=items[:20])

    def resize(self, width: int, height: int) -> None:
        """Panel boyutlarını dinamik olarak ayarla."""
        if dpg.does_item_exist("ai_left_panel"):
            # Sol panel genişliği: %38 ama en az 520px
            left_width = int(width * 0.38)
            if left_width < 520:
                left_width = 520
            dpg.configure_item("ai_left_panel", height=height, width=left_width)
            
        if dpg.does_item_exist("ai_right_panel"):
            dpg.configure_item("ai_right_panel", height=height)


def _stop_command(runner: CLICommandRunner) -> None:
    """Çalışan komutu durdurur."""
    runner.stop()


def _toggle_log_details(sender: int, app_data: Any, user_data: dict[str, str]) -> None:
    """Log detaylarını göster/gizle butonu."""
    detail_tag = user_data["detail_tag"]
    button_tag = user_data["button_tag"]
    visible = dpg.is_item_shown(detail_tag)
    dpg.configure_item(detail_tag, show=not visible)
    dpg.set_item_label(button_tag, "Debug Console" if visible else "Hide Debug Console")


def _on_keyword_store_change(sender: int, app_data: Any, user_data: dict[str, int]) -> None:
    sort_tag = user_data["sort_tag"]
    sort_label_tag = user_data["sort_label_tag"]
    is_app_store = str(app_data) == "app-store"
    dpg.configure_item(sort_tag, enabled=not is_app_store)
    dpg.set_value(
        sort_label_tag,
        "Sorting (Play Store only)" if is_app_store else "Sorting",
    )


def _on_app_id_change(sender: int, app_data: Any, user_data: dict[str, int]) -> None:
    sort_tag = user_data["sort_tag"]
    sort_label_tag = user_data["sort_label_tag"]
    is_app_store = _is_app_store_id(str(app_data))
    dpg.configure_item(sort_tag, enabled=not is_app_store)
    dpg.set_value(
        sort_label_tag,
        "Sorting (Play Store only)" if is_app_store else "Sorting",
    )


def _on_quick_tool_change(sender: int, app_data: str, user_data: dict[str, str]) -> None:
    for tool_name, group_tag in user_data.items():
        if tool_name == app_data:
            dpg.configure_item(group_tag, show=True)
        else:
            dpg.configure_item(group_tag, show=False)


def _add_help_marker(message: str) -> None:
    """Bir yardım ikonu (?) ekler ve üzerine gelince tooltip gösterir."""
    last_item = dpg.add_text("(?)", color=(137, 180, 250))
    with dpg.tooltip(last_item):
        dpg.add_text(message, wrap=400)


def _build_layout(
    runner: CLICommandRunner,
    history_panel: ResultHistoryPanel,
    ai_panel: AIAssistPanel,
    header_font: int | str | None,
) -> tuple[dict[str, int], dict[str, int], dict[str, int], dict[str, int], dict[str, int]]:
    assets_inputs: dict[str, int] = {}
    search_inputs: dict[str, int] = {}
    keyword_inputs: dict[str, int] = {}
    app_inputs: dict[str, int] = {}
    metadata_inputs: dict[str, int] = {}

    def add_header(text: str):
        header_item = dpg.add_text(text, color=(137, 180, 250))
        if header_font:
            dpg.bind_item_font(header_item, header_font)

    with dpg.tab_bar():
        with dpg.tab(label="Assets Download"):
            dpg.add_spacer(height=10)
            with dpg.group(horizontal=True):
                dpg.add_spacer(width=10)
                with dpg.group():
                    with dpg.group(horizontal=True):
                        add_header("App Store Assets")
                        dpg.add_spacer(width=5)
                        _add_help_marker(
                            "This tool allows you to download app screenshots and metadata (title, icon, etc.) "
                            "from the App Store.\n\n"
                            "Usage:\n"
                            "1. Enter App ID (e.g., com.example.app or numeric ID).\n"
                            "2. Set the output directory.\n"
                            "3. Enter country codes separated by commas (e.g., us,tr).\n"
                            "4. Click 'Download Assets'."
                        )
                    dpg.add_text("Download screenshots, videos, and metadata.", color=(166, 173, 200))
                    dpg.add_spacer(height=10)
                    
                    with dpg.group(horizontal=True):
                        dpg.add_spacer(width=10)
                        with dpg.group():
                            dpg.add_text("App ID")
                            assets_inputs["app_id"] = dpg.add_input_text(default_value="com.example.app", width=400)
                            
                            dpg.add_spacer(height=8)
                            dpg.add_text("Output Directory")
                            assets_inputs["output_dir"] = dpg.add_input_text(default_value="./app_store_assets", width=400)
                            
                            dpg.add_spacer(height=8)
                            dpg.add_text("Countries")
                            assets_inputs["countries"] = dpg.add_input_text(default_value="us,tr,jp", width=400)
                            
                            dpg.add_spacer(height=15)
                            assets_inputs["skip_pdf"] = dpg.add_checkbox(label="Skip PDF report", default_value=False)
                            dpg.add_spacer(height=15)
                            dpg.add_button(
                                label="Download Assets",
                                callback=_run_assets,
                                user_data=(assets_inputs, runner),
                                width=200,
                                height=35
                            )

        with dpg.tab(label="Quick Tools"):
            dpg.add_spacer(height=10)
            with dpg.group(horizontal=True):
                dpg.add_spacer(width=10)
                with dpg.group():
                    with dpg.group(horizontal=True):
                        add_header("Quick Tools")
                        dpg.add_spacer(width=5)
                        _add_help_marker(
                            "Quick analysis tools:\n\n"
                            "- Quick Search: Search stores by keyword and view rankings.\n"
                            "- Quick Keyword: Analyze the competition and popularity of a keyword.\n"
                            "- Quick App: Perform a detailed analysis of a specific app (reviews, ratings, etc.)."
                        )

                    dpg.add_text("Search, Keyword, and App analysis tools.", color=(166, 173, 200))
                    dpg.add_spacer(height=10)

                    # Mode Selector
                    dpg.add_radio_button(
                        items=["Quick Search", "Quick Keyword", "Quick App"],
                        default_value="Quick Search",
                        horizontal=True,
                        callback=_on_quick_tool_change,
                        user_data={
                            "Quick Search": "group_quick_search",
                            "Quick Keyword": "group_quick_keyword",
                            "Quick App": "group_quick_app",
                        }
                    )
                    dpg.add_spacer(height=15)

                    # --- Quick Search Group ---
                    with dpg.group(tag="group_quick_search"):
                        with dpg.group(horizontal=True):
                            dpg.add_text("Search for apps by keyword in stores.", color=(166, 173, 200))
                            dpg.add_spacer(width=5)
                            _add_help_marker(
                                "Quick Search allows you to find apps ranking for a specific keyword.\n"
                                "You can search in App Store, Google Play, or both simultaneously.\n"
                                "Results include app names, developers, and current rankings."
                            )
                        dpg.add_spacer(height=10)
                        with dpg.group(horizontal=True):
                            dpg.add_spacer(width=10)
                            with dpg.group():
                                dpg.add_text("Keyword")
                                search_inputs["keyword"] = dpg.add_input_text(default_value="fitness", width=400)
                                
                                dpg.add_spacer(height=8)
                                dpg.add_text("Store")
                                search_inputs["store"] = dpg.add_combo(
                                    ["both", "app-store", "play-store"], default_value="both", width=400
                                )
                                
                                dpg.add_spacer(height=8)
                                dpg.add_text("Limit")
                                search_inputs["limit"] = dpg.add_input_text(default_value="10", width=400)
                                
                                dpg.add_spacer(height=8)
                                dpg.add_text("Country Code")
                                search_inputs["country"] = dpg.add_input_text(default_value="US", width=400)
                                
                                dpg.add_spacer(height=8)
                                dpg.add_text("Language Code")
                                search_inputs["language"] = dpg.add_input_text(default_value="en", width=400)
                            
                                dpg.add_spacer(height=15)
                                dpg.add_button(
                                    label="Run Quick Search",
                                    callback=_run_quick_search,
                                    user_data=(search_inputs, runner),
                                    width=200,
                                    height=35
                                )

                    # --- Quick Keyword Group ---
                    with dpg.group(tag="group_quick_keyword", show=False):
                        with dpg.group(horizontal=True):
                            dpg.add_text("Analyze keyword performance and competition.", color=(166, 173, 200))
                            dpg.add_spacer(width=5)
                            _add_help_marker(
                                "Quick Keyword analysis helps you understand the competitive landscape.\n"
                                "It provides data on total apps, top ranked apps, and keyword popularity.\n"
                                "Useful for discovering new keyword opportunities."
                            )
                        dpg.add_spacer(height=10)
                        with dpg.group(horizontal=True):
                            dpg.add_spacer(width=10)
                            with dpg.group():
                                dpg.add_text("Keyword")
                                keyword_inputs["keyword"] = dpg.add_input_text(default_value="wordle", width=400)
                                
                                dpg.add_spacer(height=8)
                                dpg.add_text("Store")
                                keyword_inputs["store"] = dpg.add_combo(
                                    STORE_OPTIONS, default_value=STORE_OPTIONS[0], width=400
                                )
                                
                                dpg.add_spacer(height=8)
                                dpg.add_text("Limit")
                                keyword_inputs["limit"] = dpg.add_input_text(default_value="3", width=400)
                                
                                dpg.add_spacer(height=8)
                                dpg.add_text("Review Count")
                                keyword_inputs["reviews"] = dpg.add_input_text(default_value="50", width=400)
                                
                                dpg.add_spacer(height=8)
                                dpg.add_text("Country Code")
                                keyword_inputs["country"] = dpg.add_input_text(default_value="US", width=400)
                                
                                dpg.add_spacer(height=8)
                                dpg.add_text("Language Code")
                                keyword_inputs["language"] = dpg.add_input_text(default_value="en", width=400)
                                
                                dpg.add_spacer(height=8)
                                keyword_inputs["sort_label"] = dpg.add_text("Sorting")
                                keyword_inputs["sort"] = dpg.add_combo(
                                    SORT_OPTIONS, default_value=SORT_OPTIONS[0], width=400
                                )

                                dpg.configure_item(
                                    keyword_inputs["store"],
                                    callback=_on_keyword_store_change,
                                    user_data={
                                        "sort_tag": keyword_inputs["sort"],
                                        "sort_label_tag": keyword_inputs["sort_label"],
                                    },
                                )
                                _on_keyword_store_change(
                                    keyword_inputs["store"],
                                    dpg.get_value(keyword_inputs["store"]),
                                    {
                                        "sort_tag": keyword_inputs["sort"],
                                        "sort_label_tag": keyword_inputs["sort_label"],
                                    },
                                )
                                
                                dpg.add_spacer(height=15)
                                keyword_inputs["report"] = dpg.add_checkbox(label="Generate PDF report", default_value=True)
                                dpg.add_spacer(height=15)
                                dpg.add_button(
                                    label="Run Keyword Analysis",
                                    callback=_run_quick_keyword,
                                    user_data=(keyword_inputs, runner),
                                    width=220,
                                    height=35
                                )

                    # --- Quick App Group ---
                    with dpg.group(tag="group_quick_app", show=False):
                        with dpg.group(horizontal=True):
                            dpg.add_text("Detailed analysis of a specific app.", color=(166, 173, 200))
                            dpg.add_spacer(width=5)
                            _add_help_marker(
                                "Quick App analysis gives you a deep dive into a single application.\n"
                                "Fetch reviews, ratings, version history, and other metadata.\n"
                                "Great for competitor analysis or monitoring your own app."
                            )
                        dpg.add_spacer(height=10)
                        with dpg.group(horizontal=True):
                            dpg.add_spacer(width=10)
                            with dpg.group():
                                dpg.add_text("App ID")
                                app_inputs["app_id"] = dpg.add_input_text(default_value="com.example.app", width=400)
                                
                                dpg.add_spacer(height=8)
                                dpg.add_text("Review Count")
                                app_inputs["reviews"] = dpg.add_input_text(default_value="50", width=400)
                                
                                dpg.add_spacer(height=8)
                                dpg.add_text("Country Code")
                                app_inputs["country"] = dpg.add_input_text(default_value="US", width=400)
                                
                                dpg.add_spacer(height=8)
                                dpg.add_text("Language Code")
                                app_inputs["language"] = dpg.add_input_text(default_value="en", width=400)
                                
                                dpg.add_spacer(height=8)
                                app_inputs["sort_label"] = dpg.add_text("Sorting")
                                app_inputs["sort"] = dpg.add_combo(
                                    SORT_OPTIONS, default_value=SORT_OPTIONS[0], width=400
                                )

                                dpg.configure_item(
                                    app_inputs["app_id"],
                                    callback=_on_app_id_change,
                                    user_data={
                                        "sort_tag": app_inputs["sort"],
                                        "sort_label_tag": app_inputs["sort_label"],
                                    },
                                )
                                _on_app_id_change(
                                    app_inputs["app_id"],
                                    dpg.get_value(app_inputs["app_id"]),
                                    {
                                        "sort_tag": app_inputs["sort"],
                                        "sort_label_tag": app_inputs["sort_label"],
                                    },
                                )
                                
                                dpg.add_spacer(height=15)
                                app_inputs["report"] = dpg.add_checkbox(label="Generate PDF report", default_value=True)
                                dpg.add_spacer(height=15)
                                dpg.add_button(
                                    label="Run App Analysis",
                                    callback=_run_quick_app,
                                    user_data=(app_inputs, runner),
                                    width=200,
                                    height=35
                                )

        with dpg.tab(label="Metadata Keywords"):
            dpg.add_spacer(height=10)
            with dpg.group(horizontal=True):
                dpg.add_spacer(width=10)
                with dpg.group():
                    add_header("Metadata Keywords")
                    dpg.add_text("Extract keywords from app names and descriptions.", color=(166, 173, 200))
                    dpg.add_spacer(height=10)
                    
                    with dpg.group(horizontal=True):
                        dpg.add_spacer(width=10)
                        with dpg.group():
                            dpg.add_text("Keyword")
                            metadata_inputs["keyword"] = dpg.add_input_text(default_value="fitness", width=400)
                            
                            dpg.add_spacer(height=8)
                            dpg.add_text("Limit")
                            metadata_inputs["limit"] = dpg.add_input_text(default_value="20", width=400)
                            
                            dpg.add_spacer(height=8)
                            dpg.add_text("Store")
                            metadata_inputs["store"] = dpg.add_combo(
                                ["both", "app-store", "play-store"], default_value="both", width=400
                            )
                            
                            dpg.add_spacer(height=8)
                            dpg.add_text("App Store Country")
                            metadata_inputs["app_store_country"] = dpg.add_input_text(default_value="US", width=400)
                            
                            dpg.add_spacer(height=8)
                            dpg.add_text("Play Store Country")
                            metadata_inputs["play_store_country"] = dpg.add_input_text(default_value="US", width=400)
                            
                            dpg.add_spacer(height=15)
                            metadata_inputs["report"] = dpg.add_checkbox(label="Generate Markdown report", default_value=True)
                            dpg.add_spacer(height=15)
                            dpg.add_button(
                                label="Run Analysis",
                                callback=_run_metadata_keywords,
                                user_data=(metadata_inputs, runner),
                                width=200,
                                height=35
                            )

        ai_panel.build_tab()
        history_panel.build_tab()

    return assets_inputs, search_inputs, keyword_inputs, app_inputs, metadata_inputs


def _run_assets(sender: int, app_data: any, user_data: tuple[dict[str, int], CLICommandRunner]) -> None:
    inputs, runner = user_data
    app_id = dpg.get_value(inputs["app_id"]).strip()
    output_dir = dpg.get_value(inputs["output_dir"]).strip()
    countries = dpg.get_value(inputs["countries"]).strip()
    skip_pdf = dpg.get_value(inputs["skip_pdf"])

    if not app_id:
        dpg.set_value(runner.status_item, "WARNING: Please enter a valid App ID")
        runner.queue.put("\nERROR: App ID cannot be empty.\n")
        return

    if not countries:
        dpg.set_value(runner.status_item, "WARNING: Please enter at least one country code")
        runner.queue.put("\nERROR: Country codes cannot be empty.\n")
        return

    args = ["assets", "download", app_id]
    if output_dir:
        args.extend(["--output-dir", output_dir])
    if countries:
        args.extend(["--countries", countries])
    if skip_pdf:
        args.append("--no-pdf")

    runner.start("Assets download", args)


def _run_quick_search(sender: int, app_data: any, user_data: tuple[dict[str, int], CLICommandRunner]) -> None:
    inputs, runner = user_data
    keyword = dpg.get_value(inputs["keyword"]).strip()
    store = dpg.get_value(inputs["store"])
    limit = dpg.get_value(inputs["limit"]).strip()
    country = dpg.get_value(inputs["country"]).strip()
    language = dpg.get_value(inputs["language"]).strip()

    if not keyword:
        dpg.set_value(runner.status_item, "WARNING: Keyword cannot be empty")
        runner.queue.put("\nERROR: Keyword cannot be empty.\n")
        return

    try:
        limit_value = str(int(limit))
        if int(limit_value) <= 0:
            raise ValueError()
    except ValueError:
        dpg.set_value(runner.status_item, "WARNING: Limit must be a positive number")
        runner.queue.put("\nERROR: Limit must be a positive integer.\n")
        return

    if store == "both":
        args = ["quick", "search", keyword, "--limit", limit_value]
        if country:
            args.extend(["--country", country])
        if language:
            args.extend(["--language", language])
        runner.start("Quick search (both stores)", args)
    else:
        args = ["search", store, keyword, "--limit", limit_value]
        if country:
            args.extend(["--country", country])
        if store == "play-store" and language:
            args.extend(["--language", language])
        store_name = "App Store" if store == "app-store" else "Play Store"
        runner.start(f"Quick search ({store_name})", args)


def _run_quick_keyword(sender: int, app_data: any, user_data: tuple[dict[str, int], CLICommandRunner]) -> None:
    inputs, runner = user_data
    keyword = dpg.get_value(inputs["keyword"]).strip()
    store = dpg.get_value(inputs["store"])
    limit = dpg.get_value(inputs["limit"]).strip()
    reviews = dpg.get_value(inputs["reviews"]).strip()
    country = dpg.get_value(inputs["country"]).strip()
    language = dpg.get_value(inputs["language"]).strip()
    sort = dpg.get_value(inputs["sort"])
    report = dpg.get_value(inputs["report"])

    if not keyword:
        dpg.set_value(runner.status_item, "⚠️ Anahtar kelime gerekli")
        runner.queue.put("\n❌ Hata: Anahtar kelime boş olamaz.\n")
        return

    try:
        limit_value = str(int(limit))
        if int(limit_value) <= 0:
            raise ValueError()
    except ValueError:
        dpg.set_value(runner.status_item, "⚠️ Limit pozitif bir sayı olmalı")
        runner.queue.put("\n❌ Hata: Limit pozitif bir tam sayı olmalı.\n")
        return

    try:
        reviews_value = str(int(reviews))
        if int(reviews_value) <= 0:
            raise ValueError()
    except ValueError:
        dpg.set_value(runner.status_item, "⚠️ Yorum sayısı pozitif bir sayı olmalı")
        runner.queue.put("\n❌ Hata: Yorum sayısı pozitif bir tam sayı olmalı.\n")
        return

    args = [
        "quick",
        "keyword",
        keyword,
        "--store",
        store,
        "--limit",
        limit_value,
        "--reviews",
        reviews_value,
        "--country",
        country,
    ]
    if language:
        args.extend(["--language", language])
    if not report:
        args.append("--no-report")
    if store == "play-store":
        args.extend(["--sort", sort])

    runner.start("Quick keyword", args)


def _run_quick_app(sender: int, app_data: any, user_data: tuple[dict[str, int], CLICommandRunner]) -> None:
    inputs, runner = user_data
    app_id = dpg.get_value(inputs["app_id"]).strip()
    reviews = dpg.get_value(inputs["reviews"]).strip()
    country = dpg.get_value(inputs["country"]).strip()
    language = dpg.get_value(inputs["language"]).strip()
    sort = dpg.get_value(inputs["sort"])
    report = dpg.get_value(inputs["report"])

    if not app_id:
        dpg.set_value(runner.status_item, "⚠️ App ID gerekli")
        runner.queue.put("\n❌ Hata: App ID boş olamaz.\n")
        return

    try:
        reviews_value = str(int(reviews))
        if int(reviews_value) <= 0:
            raise ValueError()
    except ValueError:
        dpg.set_value(runner.status_item, "⚠️ Yorum sayısı pozitif bir sayı olmalı")
        runner.queue.put("\n❌ Hata: Yorum sayısı pozitif bir tam sayı olmalı.\n")
        return

    args = [
        "quick",
        "app",
        app_id,
        "--reviews",
        reviews_value,
        "--country",
        country,
    ]
    if language:
        args.extend(["--language", language])
    if not report:
        args.append("--no-report")
    if not _is_app_store_id(app_id):
        args.extend(["--sort", sort])

    runner.start("Quick app", args)


def _run_metadata_keywords(sender: int, app_data: any, user_data: tuple[dict[str, int], CLICommandRunner]) -> None:
    inputs, runner = user_data
    keyword = dpg.get_value(inputs["keyword"]).strip()
    limit = dpg.get_value(inputs["limit"]).strip()
    store = dpg.get_value(inputs["store"])
    app_store_country = dpg.get_value(inputs["app_store_country"]).strip()
    play_store_country = dpg.get_value(inputs["play_store_country"]).strip()
    report = dpg.get_value(inputs["report"])

    if not keyword:
        dpg.set_value(runner.status_item, "⚠️ Anahtar kelime gerekli")
        runner.queue.put("\n❌ Hata: Anahtar kelime boş olamaz.\n")
        return

    try:
        limit_value = str(int(limit))
        if int(limit_value) <= 0:
            raise ValueError()
    except ValueError:
        dpg.set_value(runner.status_item, "⚠️ Limit pozitif bir sayı olmalı")
        runner.queue.put("\n❌ Hata: Limit pozitif bir tam sayı olmalı.\n")
        return

    args = [
        "analyze",
        "metadata-keywords",
        keyword,
        "--limit",
        limit_value,
        "--store",
        store,
        "--app-store-country",
        app_store_country,
        "--play-store-country",
        play_store_country,
    ]
    
    if not report:
        args.append("--no-report")

    runner.start("Metadata Keywords", args)


def main() -> None:
    dpg.create_context()
    header_font = _ensure_turkish_font()
    modern_theme = _create_modern_theme()
    dpg.bind_theme(modern_theme)
    
    # Ana pencere
    with dpg.window(label="Screen ASO Desktop", width=1000, height=800, tag="main_window"):
        # Başlık ve durum çubuğu
        with dpg.group(horizontal=True):
            header_text = dpg.add_text("Screen ASO Desktop", color=(137, 180, 250))
            if header_font:
                dpg.bind_item_font(header_text, header_font)
            
            dpg.add_spacer(width=20)
            status_text = dpg.add_text("Ready", color=(166, 227, 161))
        
        dpg.add_spacer(height=10)
        
        # Alt panel: log çıktısı, ilerleme ve kontroller
        log_detail_group_tag = "operation_log_detail"
        log_toggle_button_tag = "operation_log_toggle"
        progress_bar_tag = "operation_log_progress"
        main_status_text_tag = "main_status_text"

        with dpg.group(horizontal=True):
            dpg.add_text("Operation Log", color=(200, 200, 200))
            dpg.add_spacer(width=-1)
            with dpg.group(horizontal=True):
                dpg.add_button(
                    label="Clear",
                    width=80,
                    callback=lambda s, a, u: runner.clear_log(),
                )
                dpg.add_button(
                    label="Stop",
                    width=80,
                    callback=lambda s, a, u: _stop_command(runner),
                )
                dpg.add_button(
                    label="Debug Console",
                    width=160,
                    tag=log_toggle_button_tag,
                    callback=_toggle_log_details,
                    user_data={
                        "detail_tag": log_detail_group_tag,
                        "button_tag": log_toggle_button_tag,
                    },
                )

        # Prominent status text
        dpg.add_text("Ready", tag=main_status_text_tag, color=(137, 180, 250))

        progress_bar = dpg.add_progress_bar(
            default_value=0.0,
            overlay="Ready",
            height=16,
            width=-1,
            tag=progress_bar_tag,
        )
        dpg.add_spacer(height=6)
        with dpg.group(tag=log_detail_group_tag, show=False):
                log_input = dpg.add_input_text(
                    multiline=True,
                    readonly=True,
                    height=200,
                    width=-1,
                    default_value="> Screen ASO ready. Use tabs to run commands.\n",
                    tag="log_output"
                )

        dpg.add_spacer(height=10)

        # Tab menüsü
        history_panel = ResultHistoryPanel()
        ai_panel = AIAssistPanel(header_font=header_font)
        runner = CLICommandRunner(log_input, status_text, progress_bar, main_status_text_tag)
        _build_layout(runner, history_panel, ai_panel, header_font)

    # Pencere boyutu değişince çalışacak callback
    def _on_resize(sender, app_data):
        # Toplam yükseklik - (Header + TabBar + Log Panel + Margins)
        viewport_width = dpg.get_viewport_width()
        viewport_height = dpg.get_viewport_height()
        
        available_height = viewport_height - 180
        if available_height < 400:
            available_height = 400
        
        # AI panelini güncelle
        ai_panel.resize(viewport_width, available_height)
        
        # Results & History panelini güncelle
        history_panel.resize(viewport_width, available_height)

    dpg.set_viewport_resize_callback(_on_resize)

    dpg.create_viewport(title="Screen ASO Desktop", width=1280, height=900)
    dpg.setup_dearpygui()
    dpg.show_viewport()
    dpg.set_primary_window("main_window", True)
    was_running = False
    while dpg.is_dearpygui_running():
        was_running = runner.running
        runner.poll()
        ai_panel.poll()
        if was_running and not runner.running:
            history_panel._refresh()
        dpg.render_dearpygui_frame()
    dpg.destroy_context()


if __name__ == "__main__":
    main()
