"""Formatting utilities for Screen ASO."""

from typing import Any, Dict, List
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.table import Table


class Formatter:
    """Output formatting utilities."""

    def __init__(self):
        self.console = Console()

    def print_success(self, message: str) -> None:
        """Print success message."""
        self.console.print(f"[green]✓[/green] {message}")

    def print_error(self, message: str) -> None:
        """Print error message."""
        self.console.print(f"[red]✗[/red] {message}")

    def print_warning(self, message: str) -> None:
        """Print warning message."""
        self.console.print(f"[yellow]⚠[/yellow] {message}")

    def print_info(self, message: str) -> None:
        """Print info message."""
        self.console.print(f"[blue]ℹ[/blue] {message}")

    def create_progress(self, description: str = "Processing..."):
        """Create a progress bar."""
        return Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=self.console,
        )

    def print_table(self, data: List[Dict[str, Any]], title: str = "") -> None:
        """Print data as a table."""
        if not data:
            self.print_warning("No data to display")
            return

        table = Table(title=title, show_header=True, header_style="bold magenta")

        # Add columns from first row
        for key in data[0].keys():
            table.add_column(key.replace("_", " ").title())

        # Add rows
        for row in data:
            table.add_row(*[str(value) for value in row.values()])

        self.console.print(table)

    def print_json(self, data: Dict[str, Any], title: str = "") -> None:
        """Print data as formatted JSON."""
        if title:
            self.console.print(f"[bold]{title}[/bold]")

        import json

        formatted_json = json.dumps(data, indent=2, ensure_ascii=False)
        self.console.print(formatted_json)

    def print_summary(self, stats: Dict[str, Any]) -> None:
        """Print summary statistics."""
        table = Table(title="Summary", show_header=False)
        table.add_column("Metric", style="cyan")
        table.add_column("Value", style="green")

        for key, value in stats.items():
            table.add_row(key.replace("_", " ").title(), str(value))

        self.console.print(table)
