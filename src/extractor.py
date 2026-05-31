"""Extractive pre-filter: TF-IDF sentence scoring to reduce text before Gemma sees it.

Splits text into sentences, scores each with TF-IDF, and keeps the top `keep_ratio`
fraction in original order. Gives Gemma a cleaner signal — less boilerplate, less
repetition — which improves abstractive compression quality and reduces input tokens.

Only called on prose-heavy inputs above a token threshold. Skipped for code-heavy
content (the caller checks via _is_prose before invoking).
"""
import math
import re
from typing import Optional


def _tokenize(text: str) -> list[str]:
    """Lowercase words only — strip punctuation, ignore single-char tokens."""
    return [w for w in re.findall(r"[a-z]{2,}", text.lower())]


def _split_sentences(text: str) -> list[str]:
    """Split on sentence-ending punctuation followed by whitespace/end.
    Keeps the delimiter attached to the preceding sentence."""
    # Split on '. ', '! ', '? ', '\n\n' boundaries
    parts = re.split(r'(?<=[.!?])\s+|\n{2,}', text.strip())
    return [p.strip() for p in parts if p.strip()]


def _tfidf_scores(sentences: list[str]) -> list[float]:
    """Return a TF-IDF-based relevance score per sentence."""
    n = len(sentences)
    if n == 0:
        return []

    # Tokenize all sentences
    tokenized = [_tokenize(s) for s in sentences]

    # Document frequency: how many sentences contain each word
    df: dict[str, int] = {}
    for tokens in tokenized:
        for word in set(tokens):
            df[word] = df.get(word, 0) + 1

    scores: list[float] = []
    for tokens in tokenized:
        if not tokens:
            scores.append(0.0)
            continue
        total = len(tokens)
        freq: dict[str, int] = {}
        for w in tokens:
            freq[w] = freq.get(w, 0) + 1
        # Average TF-IDF across the sentence's unique terms
        tfidf_sum = 0.0
        for word, count in freq.items():
            tf = count / total
            idf = math.log((n + 1) / (df.get(word, 0) + 1)) + 1.0
            tfidf_sum += tf * idf
        scores.append(tfidf_sum / len(freq))

    return scores


def pre_filter(text: str, keep_ratio: float = 0.6) -> str:
    """Keep the top `keep_ratio` fraction of sentences by TF-IDF score.

    Returns the original text unchanged when:
    - fewer than 4 sentences (nothing meaningful to drop)
    - keep_ratio >= 1.0

    Sentences are returned in their original order.
    """
    if keep_ratio >= 1.0:
        return text

    sentences = _split_sentences(text)
    if len(sentences) < 4:
        return text

    scores = _tfidf_scores(sentences)

    # Determine cutoff: keep top keep_ratio by score
    n_keep = max(1, round(len(sentences) * keep_ratio))

    # Pair (score, original_index, sentence), sort descending by score
    ranked = sorted(
        enumerate(zip(scores, sentences)),
        key=lambda x: x[1][0],
        reverse=True,
    )
    keep_indices = {idx for idx, _ in ranked[:n_keep]}

    # Reconstruct in original order
    kept = [sent for i, sent in enumerate(sentences) if i in keep_indices]
    return " ".join(kept)


def is_prose(text: str, max_code_ratio: float = 0.35) -> bool:
    """Return True if text is prose-dominant (safe to extractive-filter).

    Code indicators: lines starting with spaces/tabs (indented), backtick fences,
    import/def/class keywords, JSON/list braces. If more than max_code_ratio of
    non-empty lines look like code, skip extraction.
    """
    lines = [l for l in text.splitlines() if l.strip()]
    if not lines:
        return False

    code_patterns = re.compile(
        r'^(\s{2,}|\t)'          # indented
        r'|^```'                  # fenced code block
        r'|^(import |from |def |class |if |for |while |return )'
        r'|^\s*[\[{]'            # JSON / list
        r'|^\s*[-*+]\s+`'        # markdown code list item
    )
    code_lines = sum(1 for l in lines if code_patterns.match(l))
    return (code_lines / len(lines)) <= max_code_ratio
