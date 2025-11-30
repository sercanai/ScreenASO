# Sentiment Analysis Pipeline

Review'ları duygu analizi, aspect detection ve keyword extraction ile zenginleştirir.

## Özellikler

- 🌍 **Dil Tespiti**: 170+ dil, %99+ doğruluk
- 😊 **Sentiment Analysis**: DistilBERT (positive/negative/neutral)
- 🎯 **Aspect Detection**: pricing, performance, ux, stability, ads, support
- 🔑 **Keyword Extraction**: TF-IDF + KeyBERT
- 🏷️ **Review Classification**: bug_report, feature_request, praise, ux_feedback
- 💬 **Needs Reply**: Otomatik yanıt gereksinimi tespiti

## Hızlı Başlangıç

```python
from core.sentiment.pipeline import ReviewEnricher

enricher = ReviewEnricher()
result = enricher.analyze_review(
    body="This app is amazing! I love the dark mode.",
    rating=5.0
)

print(result["sentiment_label"])  # positive
print(result["language"])  # en
print(result["aspect_sentiment"])  # {"ux": {...}}
```

## Toplu İşleme

```bash
# Yorumları analiz et (scrape çıktısından)
aso-cli analyze reviews outputs/scrapes/*/scrape_*.json --detailed

# Keyword analizi yap
aso-cli analyze keywords outputs/scrapes/*/scrape_*.json

# İki uygulamayı karşılaştır
aso-cli analyze compare file1.json file2.json
```

## Yapılandırma

```python
from core.sentiment.pipeline import ReviewEnricher, ReviewEnricherConfig

config = ReviewEnricherConfig(
    enable_zero_shot=False,
    keyword_limit=8,
    value_phrase_limit=5,
)
enricher = ReviewEnricher(config)
```

## Çıktı Örneği

```json
{
  "language": "en",
  "sentiment_label": "negative",
  "sentiment_score": -0.99,
  "aspect_sentiment": {
    "pricing": {"label": "negative", "score": -0.99, "source": "heuristic"}
  },
  "keyword_candidates": ["premium", "expensive"],
  "needs_reply": true,
  "review_type": "payment_issue"
}
```

## Performans

| Özellik | Zero-shot Disabled | Zero-shot Enabled |
|---------|-------------------|-------------------|
| Hız | 1-2 sn/review | 10-20 sn/review |
| Aspect/review | 1.2 | 4.5 |
| Doğruluk | High precision | High recall |

**Öneriler:**
- Bulk processing (1000+ review): `enable_zero_shot=False`
- Detaylı analiz: `enable_zero_shot=True`

## Notlar

- İlk çalıştırmada modeller otomatik indirilir (~500MB)
- GPU/MPS varsa otomatik kullanılır
- Sentiment doğruluğu: ~91% (DistilBERT SST-2)
- Dil tespiti: ~95% (fastText)
