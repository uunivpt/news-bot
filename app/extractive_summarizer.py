from __future__ import annotations

import math
import re
from collections import Counter

_WORD_RE = re.compile(r"[A-Za-z][A-Za-z'-]{2,}")
_STOPWORDS = {
    "the","and","for","that","with","this","from","have","has","were","was","are",
    "their","they","said","into","after","before","about","will","been","also","than",
    "then","over","under","more","some","such","its","but","not","who","what","when",
    "where","which","while","would","could","should","officials","official","according",
    "said","says","new","latest"
}


def _tokens(sentence: str) -> list[str]:
    return [w for w in _WORD_RE.findall(sentence.lower()) if w not in _STOPWORDS]


def _tfidf_vectors(items: list[str]) -> list[dict[str, float]]:
    token_lists = [_tokens(item) for item in items]
    document_frequency = Counter()
    for tokens in token_lists:
        document_frequency.update(set(tokens))
    count = len(items)
    vectors = []
    for tokens in token_lists:
        tf = Counter(tokens)
        vector = {}
        for word, freq in tf.items():
            # Smooth IDF keeps rare concrete facts useful while avoiding
            # zero-weight terms in short news stories.
            idf = math.log((count + 1) / (document_frequency[word] + 1)) + 1.0
            vector[word] = (1.0 + math.log(freq)) * idf
        vectors.append(vector)
    return vectors


def _cosine(a: dict[str, float], b: dict[str, float]) -> float:
    if not a or not b:
        return 0.0
    if len(a) > len(b):
        a, b = b, a
    dot = sum(value * b.get(key, 0.0) for key, value in a.items())
    na = math.sqrt(sum(value * value for value in a.values()))
    nb = math.sqrt(sum(value * value for value in b.values()))
    return dot / (na * nb) if na and nb else 0.0


def _normalize(values: list[float]) -> list[float]:
    if not values:
        return []
    lo, hi = min(values), max(values)
    if hi - lo < 1e-12:
        return [1.0 for _ in values]
    return [(value - lo) / (hi - lo) for value in values]


def textrank_scores(items: list[str], damping: float = 0.85, iterations: int = 30) -> list[float]:
    """Return deterministic TextRank centrality scores for sentences."""
    if not items:
        return []
    if len(items) == 1:
        return [1.0]

    vectors = _tfidf_vectors(items)
    graph = [[0.0] * len(items) for _ in items]
    for i in range(len(items)):
        for j in range(i + 1, len(items)):
            similarity = _cosine(vectors[i], vectors[j])
            graph[i][j] = similarity
            graph[j][i] = similarity

    ranks = [1.0 / len(items)] * len(items)
    for _ in range(max(1, iterations)):
        updated = [(1.0 - damping) / len(items)] * len(items)
        for i in range(len(items)):
            incoming = 0.0
            for j in range(len(items)):
                if i == j:
                    continue
                weight_sum = sum(graph[j])
                if weight_sum:
                    incoming += graph[j][i] / weight_sum * ranks[j]
            updated[i] += damping * incoming
        if max(abs(updated[i] - ranks[i]) for i in range(len(items))) < 1e-8:
            ranks = updated
            break
        ranks = updated
    return ranks


def lexrank_scores(items: list[str], threshold: float = 0.10, iterations: int = 30) -> list[float]:
    """Return deterministic LexRank-style centrality scores.

    This is implemented directly so the bot needs no API, model, NLTK corpus,
    or downloaded runtime data.
    """
    if not items:
        return []
    if len(items) == 1:
        return [1.0]

    vectors = _tfidf_vectors(items)
    graph = [[0.0] * len(items) for _ in items]
    for i in range(len(items)):
        for j in range(i + 1, len(items)):
            similarity = _cosine(vectors[i], vectors[j])
            if similarity >= threshold:
                graph[i][j] = similarity
                graph[j][i] = similarity

    # PageRank over the thresholded sentence-similarity graph.
    ranks = [1.0 / len(items)] * len(items)
    for _ in range(max(1, iterations)):
        updated = [0.0] * len(items)
        for i in range(len(items)):
            total = sum(graph[i])
            if not total:
                updated[i] += 1.0 / len(items)
                continue
            for j in range(len(items)):
                if graph[i][j]:
                    updated[j] += ranks[i] * graph[i][j] / total
        if max(abs(updated[i] - ranks[i]) for i in range(len(items))) < 1e-8:
            ranks = updated
            break
        ranks = updated
    return ranks


def hybrid_scores(items: list[str], editorial_scores: list[float]) -> list[float]:
    """Blend TextRank/LexRank centrality with the newsroom's factual scoring."""
    if not items:
        return []
    tr = _normalize(textrank_scores(items))
    lr = _normalize(lexrank_scores(items))
    editorial = _normalize(editorial_scores)
    return [
        0.78 * editorial[i] + 0.14 * tr[i] + 0.08 * lr[i]
        for i in range(len(items))
    ]
