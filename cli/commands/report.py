"""Report commands for Screen ASO."""

from datetime import datetime
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console

from cli.utils.output import OutputManager
from cli.utils.reporting import generate_pdf_report
from cli.utils.validation import ValidationError, Validator

app = typer.Typer(help="Generate reports")
console = Console()
output_manager = OutputManager()
validator = Validator()


@app.command()
def generate(
    input: str = typer.Argument(..., help="Input JSON file with analysis data"),
    output: Optional[str] = typer.Option(
        None, "--output", "-o", help="Output PDF file (defaults to per-app folder)"
    ),
    title: str = typer.Option(
        "Screen ASO Analysis Report", "--title", "-t", help="Report title"
    ),
) -> None:
    """Generate PDF report from analysis data."""
    try:
        # Validate inputs
        input_file = validator.validate_file_exists(input)

        console.print(f"\n[bold cyan]Generating PDF Report[/bold cyan]")
        console.print(f"Input: {input}")
        console.print(f"Output: {output or '(auto)'}\n")

        data = output_manager.load_json(input_file)
        if output:
            output_path = Path(output)
        else:
            slug = output_manager.derive_slug_from_payload(data)
            base_name = Path(input).stem or "report"
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            output_path = (
                output_manager.base_dir
                / "reports"
                / slug
                / f"{base_name}_{timestamp}.pdf"
            )
        output_path = generate_pdf_report(data, output_path, title=title)

        # Verify output
        if output_path.exists():
            file_size = output_path.stat().st_size / 1024  # KB
            console.print(f"\n[green]✓[/green] Report generated successfully!")
            output_manager.print_summary(
                {
                    "Input": input,
                    "Output": str(output_path),
                    "File Size": f"{file_size:.1f} KB",
                    "Title": title,
                }
            )
        else:
            console.print("[red]✗ Report generation failed[/red]")
            raise typer.Exit(1)

    except ValidationError as e:
        console.print(f"[red]Validation error: {e}[/red]")
        raise typer.Exit(1)
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")
        import traceback

        console.print(traceback.format_exc())
        raise typer.Exit(1)
