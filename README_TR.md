# Screen ASO - Uygulama Mağazası Optimizasyon Aracı

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![CLI](https://img.shields.io/badge/CLI-Typer-orange.svg)](https://typer.tiangolo.com/)

Screen ASO, App Store ve Play Store için metadata toplama, yorum kazıma, sentiment analizi, keyword çıkarımı, asset indirme ve PDF raporlama yapan bir CLI aracıdır.

## Öne Çıkanlar

- **Modern CLI** – Typer + Rich ile progress bar ve renkli çıktı
- **Sentiment Analizi** – İngilizce dil desteği, aspect etiketleme
- **Keyword Çıkarımı** – KeyBERT ile anlamsal analiz
- **PDF Raporları** – Maskelenmiş yorumlarla profesyonel raporlar
- **Asset İndirme** – Çoklu ülke ikon ve screenshot
- **AI Assist** – Gemini/OpenRouter entegrasyonu ve host allowlist kontrolü
- **Otomatik Sansür** – Review alanları otomatik maskelenir

## Hızlı Başlangıç

```bash
# Kurulum
git clone <repository-url> && cd screenaso-v1
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt && pip install -e .
python -m crawl4ai install-browsers
aso-cli --help
```

### Temel Komutlar

```bash
# Arama
aso-cli quick search "fitness" --limit 10 --country US

# Keyword pipeline
aso-cli quick keyword "puzzle" --store play-store --limit 5 --reviews 50

# Uygulama analizi + PDF
aso-cli quick app com.example.app --reviews 100 --report

# Asset indirme
aso-cli assets download 123456789 --countries US,TR,GB
```

## Çıktı Yapısı

| Dizin | İçerik |
|-------|--------|
| `outputs/scrapes/` | Ham kazıma verileri |
| `outputs/analyses/` | Analiz sonuçları |
| `outputs/reports/` | PDF/Markdown raporlar |
| `outputs/ai_results/` | AI Assist çıktıları |
| `app_store_assets/` | İndirilen ikon/screenshot |

Tüm çıktılar slug bazlı (`<app-slug>/`) ve append-only tutulur.

## Masaüstü GUI

```bash
pip install dearpygui
python gui/screenaso_app.py
```

**Sekmeler**: Assets Download, Quick Search, Quick Keyword, Quick App, AI Assist, Results & History

## Geliştirme

```bash
# PR öncesi formatlama
python -m black core/app_store core/play_store core/sentiment cli *.py

# Smoke testler
aso-cli search app-store "test" --limit 1
aso-cli scrape app 1495297747 --reviews 5
aso-cli analyze reviews outputs/scrapes/*/scrape_*.json
aso-cli report generate outputs/analyses/aso_*.json
```

Konfigürasyon için `.env` kullanın: `APP_STORE_DEFAULT_COUNTRY`, `APP_STORE_DEFAULT_LANGUAGE`, `APP_STORE_HTTP_PROXY`

## Dokümantasyon

- Kullanım kılavuzu: `docs/USAGE.md` (CLI/quick workflow'lar, çıktılar, GUI)
- CLI referansı: `aso-cli --help` / `aso-cli quickref`
- PII sansür: `core/privacy.py`

İyi analizler!

<a href="https://github.com/unclecode/crawl4ai">
  <img src="https://raw.githubusercontent.com/unclecode/crawl4ai/main/docs/assets/powered-by-dark.svg" alt="Powered by Crawl4AI" width="200"/>
</a>
