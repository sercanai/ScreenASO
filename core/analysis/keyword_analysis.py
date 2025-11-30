#!/usr/bin/env python3
"""
Keyword Analysis Tool - Phase 1
Analyzes keywords from app descriptions and reviews.

Features:
1. Keyword frequency analysis
2. N-gram analysis (bigrams, trigrams)
3. Keyword co-occurrence analysis
"""

import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Dict, List, Any, Tuple
import argparse

from core.privacy import strip_redacted_text

# English stopwords
STOPWORDS = {
    'a', 'an', 'and', 'are', 'as', 'at', 'be', 'by', 'for', 'from', 'has', 'he',
    'in', 'is', 'it', 'its', 'of', 'on', 'that', 'the', 'to', 'was', 'will', 'with',
    'this', 'but', 'they', 'have', 'had', 'what', 'when', 'where', 'who', 'which',
    'why', 'how', 'all', 'each', 'every', 'both', 'few', 'more', 'most', 'other',
    'some', 'such', 'no', 'nor', 'not', 'only', 'own', 'same', 'so', 'than', 'too',
    'very', 'can', 'just', 'should', 'now', 'i', 'you', 'your', 'my', 'me', 'we',
    'our', 'us', 'them', 'their', 'there', 'been', 'being', 'do', 'does', 'did',
    'doing', 'would', 'could', 'ought', 'am', 'may', 'might', 'must', 'shall',
}


def clean_text(text: str) -> str:
    """Clean and normalize text while preserving Unicode letters and numbers."""
    text = text.lower()
    text = re.sub(r"http\S+|www\S+", "", text)
    # Keep all Unicode word chars, spaces and hyphens; replace other symbols with space
    text = re.sub(r"[^\w\s-]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def extract_words(
    text: str,
    remove_stopwords: bool = True,
    min_length: int = 3,
) -> List[str]:
    """Extract normalized tokens from text with optional stopword/min-length filters."""
    words = clean_text(text).split()
    min_len = max(1, min_length)
    if remove_stopwords:
        words = [w for w in words if w not in STOPWORDS and len(w) >= min_len]
    else:
        words = [w for w in words if len(w) >= min_len]
    return words


def get_ngrams(words: List[str], n: int) -> List[str]:
    """Generate n-grams from word list."""
    return [' '.join(words[i:i+n]) for i in range(len(words) - n + 1)]


def analyze_keyword_frequency(
    texts: List[str],
    top_n: int = 50,
    *,
    remove_stopwords: bool = True,
    min_length: int = 3,
) -> Dict[str, int]:
    """Analyze keyword frequency across texts."""
    all_words: List[str] = []
    for text in texts:
        all_words.extend(
            extract_words(text, remove_stopwords=remove_stopwords, min_length=min_length)
        )
    
    counter = Counter(all_words)
    return dict(counter.most_common(top_n))


def analyze_ngrams(
    texts: List[str],
    n: int,
    top_n: int = 30,
    *,
    remove_stopwords: bool = True,
    min_length: int = 3,
) -> Dict[str, int]:
    """Analyze n-grams across texts."""
    all_ngrams: List[str] = []
    for text in texts:
        words = extract_words(
            text, remove_stopwords=remove_stopwords, min_length=min_length
        )
        if len(words) >= n:
            all_ngrams.extend(get_ngrams(words, n))
    
    counter = Counter(all_ngrams)
    return dict(counter.most_common(top_n))


def analyze_cooccurrence(
    texts: List[str],
    window_size: int = 5,
    top_n: int = 30,
    *,
    remove_stopwords: bool = True,
    min_length: int = 3,
) -> Dict[str, int]:
    """Analyze keyword co-occurrence within a window."""
    cooccurrence = defaultdict(int)
    
    for text in texts:
        words = extract_words(
            text, remove_stopwords=remove_stopwords, min_length=min_length
        )
        for i, word in enumerate(words):
            # Get words within window
            start = max(0, i - window_size)
            end = min(len(words), i + window_size + 1)
            context = words[start:i] + words[i+1:end]
            
            for context_word in context:
                # Create sorted pair to avoid duplicates (word1, word2) vs (word2, word1)
                pair = tuple(sorted([word, context_word]))
                cooccurrence[pair] += 1
    
    # Convert to readable format
    cooccurrence_str = {f"{k[0]} + {k[1]}": v for k, v in cooccurrence.items()}
    return dict(sorted(cooccurrence_str.items(), key=lambda x: x[1], reverse=True)[:top_n])


def analyze_description(description: str) -> Dict[str, Any]:
    """Analyze keywords in app description."""
    return {
        "top_keywords": analyze_keyword_frequency([description], top_n=30),
        "bigrams": analyze_ngrams([description], n=2, top_n=20),
        "trigrams": analyze_ngrams([description], n=3, top_n=15),
    }


def analyze_reviews(reviews: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Analyze keywords in reviews."""
    # Extract review texts
    review_texts = []
    for review in reviews:
        title = strip_redacted_text(review.get('title'))
        body = strip_redacted_text(review.get('body') or review.get('text'))
        if title:
            review_texts.append(title)
        if body:
            review_texts.append(body)
    
    if not review_texts:
        return {
            "top_keywords": {},
            "bigrams": {},
            "trigrams": {},
            "cooccurrence": {},
        }
    
    return {
        "top_keywords": analyze_keyword_frequency(review_texts, top_n=30),
        "bigrams": analyze_ngrams(review_texts, n=2, top_n=20),
        "trigrams": analyze_ngrams(review_texts, n=3, top_n=15),
        "cooccurrence": analyze_cooccurrence(review_texts, window_size=5, top_n=20),
    }


def compare_keywords(desc_keywords: Dict[str, int], review_keywords: Dict[str, int]) -> Dict[str, Any]:
    """Compare keywords between description and reviews."""
    desc_set = set(desc_keywords.keys())
    review_set = set(review_keywords.keys())
    
    common = desc_set & review_set
    desc_only = desc_set - review_set
    review_only = review_set - desc_set
    
    return {
        "common_keywords": {k: {"description": desc_keywords[k], "reviews": review_keywords[k]} 
                           for k in sorted(common, key=lambda x: desc_keywords[x] + review_keywords[x], reverse=True)[:20]},
        "description_only": {k: desc_keywords[k] for k in sorted(desc_only, key=lambda x: desc_keywords[x], reverse=True)[:15]},
        "reviews_only": {k: review_keywords[k] for k in sorted(review_only, key=lambda x: review_keywords[x], reverse=True)[:15]},
    }


def main():
    parser = argparse.ArgumentParser(description="Keyword Analysis Tool - Phase 1")
    parser.add_argument("--input", required=True, help="Input JSON file with app data")
    parser.add_argument("--output", help="Output JSON file (default: <input>_keywords.json)")
    args = parser.parse_args()
    
    input_path = Path(args.input)
    if not input_path.exists():
        print(f"✗ Input file not found: {input_path}")
        return
    
    # Load data
    print(f"Loading data from {input_path}...")
    with open(input_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    # Handle different JSON structures
    if isinstance(data, list):
        # Play Store format: direct list
        apps = data
    elif isinstance(data, dict) and 'apps' in data:
        # App Store format: {"apps": [...]}
        apps = data['apps']
    else:
        # Single app object
        apps = [data]
    
    results = []
    
    for app in apps:
        app_id = app.get('app_id', 'unknown')
        app_name = app.get('app_name', 'Unknown App')
        
        print(f"\n{'='*60}")
        print(f"Analyzing: {app_name}")
        print(f"App ID: {app_id}")
        print(f"{'='*60}")
        
        # Analyze description (try different field names)
        description = (
            app.get('description') or 
            app.get('app_description') or 
            ''
        )
        if description:
            print(f"✓ Description: {len(description)} chars")
            desc_analysis = analyze_description(description)
        else:
            print("✗ No description found")
            desc_analysis = {"top_keywords": {}, "bigrams": {}, "trigrams": {}}
        
        # Analyze reviews
        reviews = app.get('reviews', [])
        print(f"✓ Reviews: {len(reviews)} found")
        review_analysis = analyze_reviews(reviews)
        
        # Compare
        comparison = compare_keywords(
            desc_analysis['top_keywords'],
            review_analysis['top_keywords']
        )
        
        result = {
            "app_id": app_id,
            "app_name": app_name,
            "country": app.get('country'),
            "language": app.get('language'),
            "analysis": {
                "description": desc_analysis,
                "reviews": review_analysis,
                "comparison": comparison,
            },
            "stats": {
                "description_length": len(description),
                "reviews_count": len(reviews),
                "unique_keywords_description": len(desc_analysis['top_keywords']),
                "unique_keywords_reviews": len(review_analysis['top_keywords']),
            }
        }
        
        results.append(result)
        
        # Print summary
        print(f"\n📊 Summary:")
        print(f"  Description keywords: {len(desc_analysis['top_keywords'])}")
        print(f"  Review keywords: {len(review_analysis['top_keywords'])}")
        print(f"  Common keywords: {len(comparison['common_keywords'])}")
        print(f"  Description-only: {len(comparison['description_only'])}")
        print(f"  Reviews-only: {len(comparison['reviews_only'])}")
    
    # Save results
    if args.output:
        output_path = Path(args.output)
    else:
        output_path = input_path.parent / f"{input_path.stem}_keywords.json"
    
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
    
    print(f"\n{'='*60}")
    print(f"✓ Analysis saved to: {output_path}")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
