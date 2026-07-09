"""Embedding service — local fastembed, API fallback, or disabled.

Three tiers controlled by ``CORECODER_EMBEDDING_PROVIDER``:

    "local"  — fastembed + BAAI/bge-small-zh-v1.5 (default, ~400 MB)
    "api"    — OpenAI-compatible /v1/embeddings (zero extra deps)
    "none"   — no embeddings, FTS5 only

The local model is lazy-loaded on first use and cached for the
process lifetime.  If the model fails to load (missing deps, bad
platform), we silently fall back to "none" mode.
"""

from __future__ import annotations

import logging
import sys
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from openai import OpenAI

logger = logging.getLogger(__name__)


class EmbeddingService:
    """Produce vector embeddings for text, with graceful degradation."""

    def __init__(
        self,
        provider: str = "local",
        model: str = "BAAI/bge-small-zh-v1.5",
        dims: int = 512,
        api_key: str = "",
        base_url: str | None = None,
    ):
        self.provider = provider
        self.model = model
        self.dims = dims
        self._api_key = api_key
        self._base_url = base_url
        self._local_model = None   # lazy-loaded fastembed model
        self._client = None        # lazy-loaded OpenAI client for api mode

    # ---- public API ----

    def is_available(self) -> bool:
        """Return True if embeddings can be produced."""
        return self.provider != "none"

    def embed(self, text: str) -> list[float] | None:
        """Generate an embedding for *text*.  Returns None on failure."""
        if not text or not text.strip():
            return None

        if self.provider == "local":
            return self._embed_local(text)
        elif self.provider == "api":
            return self._embed_api(text)
        else:
            return None

    def embed_batch(self, texts: list[str]) -> list[list[float] | None]:
        """Generate embeddings for multiple texts.

        Individual failures return None in the corresponding position
        rather than failing the entire batch.
        """
        if not texts:
            return []

        if self.provider == "local":
            return self._embed_batch_local(texts)
        elif self.provider == "api":
            return self._embed_batch_api(texts)
        else:
            return [None] * len(texts)

    # ---- local: fastembed ----

    def _ensure_local_model(self):
        """Lazy-load the fastembed model."""
        if self._local_model is not None:
            return

        try:
            from fastembed import TextEmbedding
            self._local_model = TextEmbedding(self.model)
            logger.info("Loaded local embedding model: %s", self.model)
        except Exception as e:
            logger.warning("Failed to load local embedding model: %s", e)
            logger.warning("Falling back to 'none' embedding mode")
            self.provider = "none"

    def _embed_local(self, text: str) -> list[float] | None:
        self._ensure_local_model()
        if self._local_model is None:
            return None
        try:
            results = list(self._local_model.embed([text]))
            return results[0].tolist() if results else None
        except Exception as e:
            logger.warning("Local embedding failed: %s", e)
            return None

    def _embed_batch_local(self, texts: list[str]) -> list[list[float] | None]:
        self._ensure_local_model()
        if self._local_model is None:
            return [None] * len(texts)
        try:
            results = list(self._local_model.embed(texts))
            return [r.tolist() for r in results]
        except Exception as e:
            logger.warning("Local batch embedding failed: %s", e)
            return [None] * len(texts)

    # ---- api: OpenAI-compatible ----

    def _ensure_api_client(self):
        """Lazy-create the OpenAI client."""
        if self._client is not None:
            return
        try:
            from openai import OpenAI
            self._client = OpenAI(api_key=self._api_key, base_url=self._base_url)
        except Exception as e:
            logger.warning("Failed to create API client: %s", e)
            self.provider = "none"

    def _embed_api(self, text: str) -> list[float] | None:
        self._ensure_api_client()
        if self._client is None:
            return None
        try:
            resp = self._client.embeddings.create(model=self.model, input=text)
            return resp.data[0].embedding
        except Exception as e:
            logger.warning("API embedding failed: %s", e)
            return None

    def _embed_batch_api(self, texts: list[str]) -> list[list[float] | None]:
        self._ensure_api_client()
        if self._client is None:
            return [None] * len(texts)
        try:
            resp = self._client.embeddings.create(model=self.model, input=texts)
            # results may not be in order; sort by index
            sorted_data = sorted(resp.data, key=lambda d: d.index)
            return [d.embedding for d in sorted_data]
        except Exception as e:
            logger.warning("API batch embedding failed: %s", e)
            return [None] * len(texts)
