"""Main CLI entry point using Typer."""

import typer
from rich.console import Console

from cli.commands import search, scrape, analyze, assets, report, pipeline, quick

app = typer.Typer(
    name="aso-cli",
    help="🚀 Screen ASO - Professional App Store Optimization Tool",
    no_args_is_help=False,  # We'll handle it ourselves
    rich_markup_mode="rich",
    add_completion=False,  # We'll add it manually
    invoke_without_command=True,  # Allow callback to run without command
)

console = Console()

# Add command groups
app.add_typer(search.app, name="search", help="🔍 Search apps in stores")
app.add_typer(scrape.scrape_app, name="scrape", help="📱 Scrape app data and reviews")
app.add_typer(analyze.app, name="analyze", help="📊 Analyze app data with sentiment analysis")
app.add_typer(assets.app, name="assets", help="🎨 Download app assets (icons, screenshots)")
app.add_typer(report.app, name="report", help="📄 Generate PDF reports")
app.add_typer(pipeline.app, name="pipeline", help="🔄 Run automated analysis pipelines")
app.add_typer(quick.app, name="quick", help="⚡️ Predefined end-to-end workflows")


@app.command()
def quickref() -> None:
    """Show quick reference guide with examples."""
    from rich.table import Table
    from rich.panel import Panel

    # Create main help panel
    help_text = """
🚀 [bold cyan]Screen ASO Quick Reference[/bold cyan]

[basic_workflow]Basic Workflow:[/basic_workflow]
  1️⃣ Search:  aso-cli search app-store "fitness" --limit 10
  2️⃣ Scrape:   aso-cli scrape app 123456789 --reviews 100
  3️⃣ Analyze:  aso-cli analyze reviews outputs/scrapes/*.json

[quick_workflow]Quick Workflows:[/quick_workflow]
  ⚡ Search both stores:   aso-cli quick search "fitness" --limit 10
  📊 Reports:    aso-cli report pdf outputs/analyses/*.json
  🎨 Assets:     aso-cli assets download 123456789 --countries US,TR,GB

[pro_tips]Pro Tips:[/pro_tips]
  • Auto-detect: Numeric ID = App Store, com.package = Play Store
  • Chain commands: Use output files from previous commands
  • JSON format: All outputs are structured for easy parsing
    """

    console.print(Panel(help_text.expandtabs(2), title="Quick Reference", border_style="cyan"))

    # Create examples table
    table = Table(title="Common Examples", show_header=True, header_style="bold magenta")
    table.add_column("Command", style="cyan", width=40)
    table.add_column("Description", style="white")

    table.add_row(
        "aso-cli search app-store 'fitness' --country TR",
        "Search fitness apps in Turkish store"
    )
    table.add_row(
        "aso-cli scrape app 1495297747 --reviews 200",
        "Scrape Instagram app with 200 reviews"
    )
    table.add_row(
        "aso-cli analyze reviews app_data.json --detailed",
        "Analyze reviews with detailed sentiment breakdown"
    )
    table.add_row(
        "aso-cli assets download 123456 --countries US,TR",
        "Download app icons for multiple countries"
    )
    table.add_row(
        "aso-cli report pdf analysis_results.json",
        "Generate professional PDF report"
    )
    table.add_row(
        "aso-cli quick keyword \"fitness\" --store play-store",
        "Search + scrape + analyze + report in one go"
    )

    console.print(table)
    console.print("\n[dim]For detailed help: aso-cli [command] --help[/dim]")


@app.command()
def help() -> None:
    """Show beautiful help guide with examples and visual layout."""
    from rich.panel import Panel
    from rich.table import Table
    from rich.columns import Columns
    from rich.text import Text

    # Main header with gradient effect simulation
    header_text = Text("🚀 Screen ASO - App Store Optimization", style="bold cyan")
    subheader = Text("Professional command-line tool for mobile app analysis", style="dim")

    console.print()
    console.print(Panel(header_text + "\n" + subheader, border_style="cyan", padding=(1, 2)))

    # Quick workflows section
    quick_title = Text("⚡ Quick Workflows", style="bold green")
    console.print("\n", quick_title)

    quick_table = Table(box=None, show_header=False)
    quick_table.add_column("Command", style="cyan", width=45)
    quick_table.add_column("Açıklama", style="white")

    quick_table.add_row(
        "aso-cli quick search \"fitness\" --limit 10 --country US",
        "Aynı anahtar kelimeyi App Store + Play Store'da arar ve tek JSON üretir",
    )
    quick_table.add_row(
        "aso-cli quick keyword \"puzzle\" --store play-store --limit 3 --reviews 50 --sort most_relevant",
        "Arama → seçili uygulamaları scrape et → analiz et → PDF oluştur",
    )
    quick_table.add_row(
        "aso-cli quick app com.example.app --reviews 100 --language en --sort newest --report",
        "ID'den store'u algılar, tek komutta scrape + analiz + opsiyonel PDF çalıştırır",
    )

    console.print(quick_table)

    # Manual examples section
    manual_title = Text("🛠️ Manuel Akış Örnekleri", style="bold yellow")
    console.print("\n", manual_title)

    manual_table = Table(box=None, show_header=False)
    manual_table.add_column("Command", style="cyan", width=40)
    manual_table.add_column("Açıklama", style="white")

    manual_table.add_row("aso-cli search app-store 'fitness' --limit 10", "Sadece App Store araması yap")
    manual_table.add_row("aso-cli scrape app 123456789 --reviews 100", "Seçtiğin app için ham veri topla")
    manual_table.add_row("aso-cli analyze reviews outputs/scrapes/app_*.json", "Scrape çıktısından sentiment üret")
    manual_table.add_row("aso-cli report generate outputs/analyses/aso_*.json", "JSON'dan PDF üret")
    manual_table.add_row("aso-cli assets download 123456789 --countries US,TR", "Çoklu ülkeden asset indir")

    console.print(manual_table)

    # Command overview
    commands_title = Text("📚 Available Commands", style="bold blue")
    console.print("\n", commands_title)

    # Create two-column layout for commands
    left_commands = Table(box=None, show_header=False)
    left_commands.add_column("", style="cyan", width=20)
    left_commands.add_column("", style="white")

    left_commands.add_row("⚡ quick", "Hazır workflow'lar (search/keyword/app)")
    left_commands.add_row("🔍 search", "Store bazlı arama")
    left_commands.add_row("📱 scrape", "Yorum + metadata çek")
    left_commands.add_row("📊 analyze", "Sentiment & keyword analizleri")

    right_commands = Table(box=None, show_header=False)
    right_commands.add_column("", style="cyan", width=20)
    right_commands.add_column("", style="white")

    right_commands.add_row("🎨 assets", "Download icons & screenshots")
    right_commands.add_row("📄 report", "Generate PDF reports")

    console.print(Columns([left_commands, right_commands], equal=True, expand=True))

    # Tips section
    tips_title = Text("💡 Pro Tips", style="bold yellow")
    tips_content = Text("""
• Auto-detect stores: 123456 → App Store, com.app → Play Store
• Chain commands: Use output files from previous commands
• JSON format: All outputs structured for easy parsing
• Quick reference: aso-cli quickref for detailed examples
• Global help: aso-cli [command] --help for specific help
    """.strip(), style="dim")

    console.print("\n", tips_title)
    console.print(Panel(tips_content, border_style="yellow", padding=(1, 2)))

    # Footer
    console.print("\n[dim]For detailed documentation and examples, run: aso-cli quickref[/dim]")


@app.callback()
def main(
    ctx: typer.Context,
    version: bool = typer.Option(
        False, "--version", "-v", help="Show version and exit"
    ),
    verbose: bool = typer.Option(False, "--verbose", help="Enable verbose output"),
) -> None:
    """Screen ASO - Comprehensive tool for App Store Optimization analysis."""

    if version:
        console.print(f"aso-cli version 0.1.0")
        raise typer.Exit()

    # If no command provided, show beautiful help instead of default
    if ctx.invoked_subcommand is None:
        from rich.panel import Panel
        from rich.table import Table
        from rich.columns import Columns
        from rich.text import Text

        # Main header
        header_text = Text("🚀 Screen ASO - App Store Optimization", style="bold cyan")
        subheader = Text("Professional command-line tool for mobile app analysis", style="dim")

        console.print()
        console.print(Panel(header_text + "\n" + subheader, border_style="cyan", padding=(1, 2)))

        quick_panel = Panel(
            "\n".join(
                [
                    "[bold green]⚡ Quick Başlangıç[/bold green]",
                    "1) [cyan]aso-cli quick search \"fitness\" --limit 10 --country US[/cyan]",
                    "   • Aynı keyword'ü iki store’da arar, tek JSON üretir.",
                    "2) [cyan]aso-cli quick keyword \"puzzle\" --store play-store --limit 3 --reviews 50 --sort most_relevant[/cyan]",
                    "   • Arama → scrape → analiz → PDF zinciri (yorumlar çıktıda maskelenir).",
                    "3) [cyan]aso-cli quick app com.example.app --reviews 100 --language en --sort newest --report[/cyan]",
                    "   • ID’den store’u algılayıp tek komutta tam analiz + opsiyonel PDF.",
                ]
            ),
            border_style="green",
            padding=(1, 2),
        )
        console.print("\n", quick_panel)

        manual_panel = Panel(
            "\n".join(
                [
                    "[bold yellow]🛠️ Manuel Adımlar[/bold yellow]",
                    "• Store araması:  [cyan]aso-cli search app-store \"fitness\" --limit 10[/cyan]",
                    "• Ham veri çek:   [cyan]aso-cli scrape app 123456789 --reviews 100[/cyan]",
                    "• Review analizi: [cyan]aso-cli analyze reviews outputs/scrapes/app_*.json --detailed[/cyan]",
                    "• PDF üret:       [cyan]aso-cli report generate outputs/analyses/aso_*.json[/cyan]",
                ]
            ),
            border_style="yellow",
            padding=(1, 2),
        )
        console.print("\n", manual_panel)

        tools_panel = Panel(
            "\n".join(
                [
                    "[bold blue]📚 Komut Grupları[/bold blue]",
                    "⚡ quick    – Hazır workflow setleri",
                    "🔍 search   – Store bazlı arama",
                    "📱 scrape   – Yorum + metadata toplama",
                    "📊 analyze  – Sentiment / keyword analizleri",
                    "🎨 assets   – Icon / screenshot indir",
                    "📄 report   – JSON'dan PDF üret",
                ]
            ),
            border_style="blue",
            padding=(1, 2),
        )
        console.print("\n", tools_panel)

        tips_panel = Panel(
            "\n".join(
                [
                    "[bold magenta]💡 İpuçları[/bold magenta]",
                    "• Tüm quick çıktıları `outputs/<kategori>/<app-slug>/` altında tutulur.",
                    "• Güvenlik: JSON/PDF dosyalarında review title/body alanları `[REDACTED]` olarak kaydedilir.",
                    "• `aso-cli quickref` veya `aso-cli [komut] --help` ile detaylara erişebilirsin.",
                    "• Store auto-detect: 123456 → App Store, com.app → Play Store.",
                ]
            ),
            border_style="magenta",
            padding=(1, 2),
        )
        console.print("\n", tips_panel)

        console.print("\n[dim]Quick akışlarla başlayın veya 'aso-cli quickref' komutuna göz atın[/dim]")
        raise typer.Exit()


if __name__ == "__main__":
    app()
