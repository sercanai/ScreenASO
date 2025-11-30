#!/usr/bin/env python3
"""Analyze sentiment results."""

import json
import sys
from collections import Counter
from pathlib import Path

def analyze_results(input_file: str):
    """Analyze sentiment analysis results."""
    
    with open(input_file, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    # Detect format (App Store vs Play Store)
    if isinstance(data, dict) and 'apps' in data:
        # App Store format: {"query": {...}, "apps": [...]}
        apps = data['apps']
    elif isinstance(data, list):
        # Play Store format: [{"app_id": ..., "reviews": [...]}, ...]
        apps = data
    else:
        print(f"Error: Unknown JSON format")
        sys.exit(1)
    
    # Collect stats
    total_reviews = 0
    sentiment_counts = Counter()
    aspect_counts = Counter()
    review_type_counts = Counter()
    needs_reply_count = 0
    has_language = 0
    
    for app in apps:
        for review in app.get('reviews', []):
            total_reviews += 1
            
            # Check if analysis is nested or flat
            analysis = review.get('sentiment_analysis', {})
            if not analysis:
                # Try flat format (fields directly in review)
                if 'sentiment_label' in review:
                    analysis = review
                else:
                    continue
            
            # Sentiment
            sentiment_counts[analysis.get('sentiment_label', 'unknown')] += 1
            
            # Language
            if analysis.get('language'):
                has_language += 1
            
            # Aspects
            for aspect in analysis.get('aspect_sentiment', {}).keys():
                aspect_counts[aspect] += 1
            
            # Review type
            review_type_counts[analysis.get('review_type', 'unknown')] += 1
            
            # Needs reply
            if analysis.get('needs_reply'):
                needs_reply_count += 1
    
    # Print report
    print(f"\n{'='*60}")
    print(f"SENTIMENT ANALYSIS REPORT")
    print(f"{'='*60}\n")
    
    print(f"Total Reviews: {total_reviews}\n")
    
    print("Sentiment Distribution:")
    for sentiment, count in sentiment_counts.most_common():
        pct = (count / total_reviews * 100) if total_reviews > 0 else 0
        print(f"  {sentiment:12s}: {count:4d} ({pct:5.1f}%)")
    
    print(f"\nLanguage Detection:")
    print(f"  Detected: {has_language} ({has_language/total_reviews*100:.1f}%)")
    print(f"  Unknown:  {total_reviews - has_language} ({(total_reviews-has_language)/total_reviews*100:.1f}%)")
    
    print(f"\nTop Aspects Mentioned:")
    for aspect, count in aspect_counts.most_common(10):
        print(f"  {aspect:15s}: {count:4d}")
    
    print(f"\nReview Types:")
    for rtype, count in review_type_counts.most_common():
        pct = (count / total_reviews * 100) if total_reviews > 0 else 0
        print(f"  {rtype:20s}: {count:4d} ({pct:5.1f}%)")
    
    print(f"\nNeeds Reply: {needs_reply_count} ({needs_reply_count/total_reviews*100:.1f}%)")
    
    print(f"\n{'='*60}\n")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python analyze_results.py <input_file>")
        sys.exit(1)
    
    analyze_results(sys.argv[1])
