"""Numeric retrieval core: tokenizer, BM25, dense LSI, and RRF fusion.

This module is deliberately free of project imports and of any vendor client.
It is the only place where ranking arithmetic lives, which makes it directly
testable and keeps `contracts.py` free of numerics.

Nothing here is an approved configuration. `ME-000C` is open; `k1`, `b`,
dimensionality and `rrf_k` are experiment parameters supplied by the caller and
recorded with every result.

Dense retrieval uses TF-IDF followed by truncated SVD (latent semantic
indexing). This is a genuine dense vector method that requires no model
download, so the evaluation is reproducible offline. It is **not** a
transformer embedding and must not be reported as one; `EmbeddingBackend`
exists so a transformer backend can replace it without touching this module's
callers.
"""

from __future__ import annotations

import math
import re
import unicodedata
from collections import Counter
from collections.abc import Iterable, Sequence
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    import numpy as np
    import numpy.typing as npt

_TOKEN_PATTERN = re.compile(r"[0-9a-z]+")

DEFAULT_BM25_K1 = 0.9
DEFAULT_BM25_B = 0.4
DEFAULT_RRF_K = 60
DEFAULT_DIMENSIONS = 256


def tokenize(text: str) -> list[str]:
    """Unicode-normalize, casefold, and split on alphanumeric runs.

    Deterministic and language-agnostic. Identified as
    `unicode_lower_alnum_v1`; any behavioural change requires a new identifier
    because previously recorded runs would otherwise become irreproducible.
    """

    normalized = unicodedata.normalize("NFKC", text).casefold()
    return _TOKEN_PATTERN.findall(normalized)


class BM25Index:
    """Okapi BM25 over an in-memory corpus.

    Scores use the standard IDF variant with the +1 shift, which keeps the
    weight of a term appearing in more than half the corpus positive rather
    than negative.
    """

    def __init__(
        self,
        doc_ids: Sequence[str],
        documents: Sequence[str],
        *,
        k1: float = DEFAULT_BM25_K1,
        b: float = DEFAULT_BM25_B,
    ) -> None:
        if len(doc_ids) != len(documents):
            raise ValueError("doc_ids and documents must be the same length")
        if not doc_ids:
            raise ValueError("an empty corpus cannot be indexed")
        if len(set(doc_ids)) != len(doc_ids):
            raise ValueError("doc_ids must be unique")
        self.doc_ids = list(doc_ids)
        self.k1 = float(k1)
        self.b = float(b)

        self._tokens: list[Counter[str]] = [Counter(tokenize(text)) for text in documents]
        self._lengths: list[int] = [sum(counts.values()) for counts in self._tokens]
        total = sum(self._lengths)
        self._avg_length = total / len(self._lengths) if self._lengths else 0.0

        postings: dict[str, list[tuple[int, int]]] = {}
        for index, counts in enumerate(self._tokens):
            for term, frequency in counts.items():
                postings.setdefault(term, []).append((index, frequency))
        self._postings = postings

        count = len(self._tokens)
        self._idf = {
            term: math.log(1.0 + (count - len(entries) + 0.5) / (len(entries) + 0.5))
            for term, entries in postings.items()
        }

    @property
    def size(self) -> int:
        """Number of indexed documents."""

        return len(self.doc_ids)

    def search(self, query: str, limit: int) -> list[tuple[str, float]]:
        """Return up to `limit` `(doc_id, score)` pairs, best first.

        Ties break on document id so that repeated runs of the same query
        against the same corpus produce byte-identical orderings.
        """

        if limit < 1:
            raise ValueError("limit must be positive")
        scores: dict[int, float] = {}
        for term in tokenize(query):
            entries = self._postings.get(term)
            if entries is None:
                continue
            idf = self._idf[term]
            for index, frequency in entries:
                length_norm = (
                    1.0
                    - self.b
                    + self.b
                    * (self._lengths[index] / self._avg_length if self._avg_length else 0.0)
                )
                denominator = frequency + self.k1 * length_norm
                if denominator == 0.0:
                    continue
                scores[index] = scores.get(index, 0.0) + idf * (
                    frequency * (self.k1 + 1.0) / denominator
                )
        ranked = sorted(scores.items(), key=lambda item: (-item[1], self.doc_ids[item[0]]))
        return [(self.doc_ids[index], score) for index, score in ranked[:limit]]


class EmbeddingBackend(Protocol):
    """Swappable embedding provider.

    A transformer backend satisfies this by implementing the same two methods;
    no caller of `DenseIndex` needs to change.
    """

    def fit_transform(self, documents: Sequence[str]) -> npt.NDArray[np.float64]: ...

    def transform(self, texts: Sequence[str]) -> npt.NDArray[np.float64]: ...


class _FeatureMatrix(Protocol):
    """Minimal fitted TF-IDF matrix surface used to size the latent space."""

    shape: tuple[int, int]


class _Vectorizer(Protocol):
    """Internal structural type for the lazily imported vectorizer."""

    def fit_transform(self, documents: Sequence[str]) -> _FeatureMatrix: ...

    def transform(self, texts: Sequence[str]) -> object: ...


class _SvdTransformer(Protocol):
    """Internal structural type for the fitted truncated-SVD transformer."""

    def fit_transform(self, matrix: object) -> npt.NDArray[np.float64]: ...

    def transform(self, matrix: object) -> npt.NDArray[np.float64]: ...


class TfidfSvdBackend:
    """TF-IDF followed by truncated SVD, L2-normalized (classical LSI)."""

    method = "tfidf_svd_v1"

    def __init__(self, *, dimensions: int = DEFAULT_DIMENSIONS, random_state: int = 0) -> None:
        if dimensions < 2:
            raise ValueError("dimensions must be at least two")
        self.dimensions = dimensions
        self.random_state = random_state
        self._vectorizer: _Vectorizer | None = None
        self._svd: _SvdTransformer | None = None

    def fit_transform(self, documents: Sequence[str]) -> npt.NDArray[np.float64]:
        """Fit the vocabulary and latent space on the corpus, return embeddings."""

        import numpy as np
        from sklearn.decomposition import TruncatedSVD  # type: ignore[import-untyped]
        from sklearn.feature_extraction.text import (  # type: ignore[import-untyped]
            TfidfVectorizer,
        )
        from sklearn.preprocessing import normalize  # type: ignore[import-untyped]

        self._vectorizer = TfidfVectorizer(
            tokenizer=tokenize,
            lowercase=False,
            token_pattern=None,
            sublinear_tf=True,
        )
        matrix = self._vectorizer.fit_transform(documents)
        # SVD components cannot exceed min(n_samples, n_features) - 1.
        maximum = min(matrix.shape) - 1
        if maximum < 2:
            raise ValueError("corpus must support at least two LSI dimensions")
        usable = min(self.dimensions, maximum)
        self._svd = TruncatedSVD(n_components=usable, random_state=self.random_state)
        return np.asarray(normalize(self._svd.fit_transform(matrix)), dtype=np.float64)

    def transform(self, texts: Sequence[str]) -> npt.NDArray[np.float64]:
        """Project new text into the fitted latent space."""

        if self._vectorizer is None or self._svd is None:
            raise RuntimeError("fit_transform must be called before transform")
        import numpy as np
        from sklearn.preprocessing import normalize

        vectorizer = self._vectorizer
        svd = self._svd
        return np.asarray(
            normalize(svd.transform(vectorizer.transform(texts))),
            dtype=np.float64,
        )


class DenseIndex:
    """Cosine-similarity search over embeddings from any `EmbeddingBackend`."""

    def __init__(
        self,
        doc_ids: Sequence[str],
        documents: Sequence[str],
        *,
        backend: EmbeddingBackend | None = None,
        dimensions: int = DEFAULT_DIMENSIONS,
        random_state: int = 0,
    ) -> None:
        if len(doc_ids) != len(documents):
            raise ValueError("doc_ids and documents must be the same length")
        if not doc_ids:
            raise ValueError("an empty corpus cannot be indexed")
        if len(set(doc_ids)) != len(doc_ids):
            raise ValueError("doc_ids must be unique")
        self.doc_ids = list(doc_ids)
        self.backend = backend or TfidfSvdBackend(
            dimensions=dimensions,
            random_state=random_state,
        )
        self._matrix = self.backend.fit_transform(list(documents))

    @property
    def size(self) -> int:
        """Number of indexed documents."""

        return len(self.doc_ids)

    @property
    def dimensions(self) -> int:
        """Actual latent dimensionality, which may be below the request."""

        return int(self._matrix.shape[1])

    def search(self, query: str, limit: int) -> list[tuple[str, float]]:
        """Return up to `limit` `(doc_id, cosine)` pairs, best first."""

        if limit < 1:
            raise ValueError("limit must be positive")
        import numpy as np

        vector = self.backend.transform([query])
        similarities = np.asarray(self._matrix @ vector.T).ravel()
        order = sorted(
            range(len(self.doc_ids)),
            key=lambda index: (-float(similarities[index]), self.doc_ids[index]),
        )
        return [(self.doc_ids[index], float(similarities[index])) for index in order[:limit]]


def reciprocal_rank_fusion(
    rankings: Iterable[Sequence[tuple[str, float]]],
    *,
    k: int = DEFAULT_RRF_K,
    limit: int | None = None,
) -> list[tuple[str, float]]:
    """Fuse ranked lists by reciprocal rank.

    RRF deliberately ignores the component scores and uses only positions, so
    lists with incomparable score scales (BM25 versus cosine) can be combined
    without normalization assumptions.
    """

    if k < 1:
        raise ValueError("k must be positive")
    fused: dict[str, float] = {}
    for ranking in rankings:
        for position, (doc_id, _score) in enumerate(ranking, start=1):
            fused[doc_id] = fused.get(doc_id, 0.0) + 1.0 / (k + position)
    ordered = sorted(fused.items(), key=lambda item: (-item[1], item[0]))
    return ordered if limit is None else ordered[:limit]


def component_ranks(ranking: Sequence[tuple[str, float]]) -> dict[str, int]:
    """Map each document id to its 1-based position in a ranked list."""

    return {doc_id: position for position, (doc_id, _s) in enumerate(ranking, start=1)}
