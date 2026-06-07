"""
Stage 7a: Embedding generation.

Wraps sentence-transformers with lazy loading, batching, and a simple protocol
so tests can inject a mock without importing the full ML stack.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from .models import SemanticChunk

if TYPE_CHECKING:
    from sentence_transformers import SentenceTransformer

    from .config import PipelineConfig

# Public default models -------------------------------------------------------
DEFAULT_MODEL = "BAAI/bge-large-en-v1.5"  # highest quality for technical docs
FAST_MODEL = "all-MiniLM-L6-v2"  # ~5× faster; good for development


# ── Protocol (allows test mocks without inheriting from EmbeddingModel) ──────


@runtime_checkable
class EmbedderProtocol(Protocol):
    def embed_chunks(self, chunks: list[SemanticChunk]) -> list[list[float]]: ...
    def embed_query(self, query: str) -> list[float]: ...


# ── Concrete implementation ───────────────────────────────────────────────────


class EmbeddingModel:
    """
    Thin wrapper around a sentence-transformers model.

    The model is downloaded on first use; subsequent calls reuse the cached
    weights from ``~/.cache/huggingface`` (or *cache_dir* if set).
    """

    def __init__(
        self,
        model_name: str = DEFAULT_MODEL,
        batch_size: int = 32,
        cache_dir: Path | None = None,
    ) -> None:
        self.model_name = model_name
        self.batch_size = batch_size
        self._cache_dir = cache_dir
        self._model: SentenceTransformer | None = None  # lazy

    # ── Private ──────────────────────────────────────────────────────────────

    def _load(self) -> None:
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as exc:
            raise ImportError(
                "sentence-transformers is not installed.\nRun: pip install sentence-transformers"
            ) from exc

        kwargs = {}
        if self._cache_dir is not None:
            kwargs["cache_folder"] = str(self._cache_dir)

        self._model = SentenceTransformer(self.model_name, **kwargs)

    @property
    def model(self) -> SentenceTransformer:
        if self._model is None:
            self._load()
        assert self._model is not None  # _load populates it
        return self._model

    # ── Public ────────────────────────────────────────────────────────────────

    def embed(
        self,
        texts: list[str],
        normalize: bool = True,
    ) -> list[list[float]]:
        """Embed a list of texts; returns a list of float vectors."""
        vectors = self.model.encode(
            texts,
            normalize_embeddings=normalize,
            batch_size=self.batch_size,
            show_progress_bar=len(texts) > 100,
        )
        vecs: list[list[float]] = vectors.tolist()
        return vecs

    def embed_chunks(self, chunks: list[SemanticChunk]) -> list[list[float]]:
        """Embed a list of :class:`SemanticChunk` objects using enriched text."""
        return self.embed([c.to_embed_text() for c in chunks])

    def embed_query(self, query: str) -> list[float]:
        """Embed a single search query string."""
        return self.embed([query])[0]

    @property
    def dimension(self) -> int:
        """Return the embedding vector size."""
        dim = self.model.get_sentence_embedding_dimension()
        if dim is None:
            raise RuntimeError(f"Model {self.model_name!r} reported no embedding dimension.")
        return dim


# ── Azure OpenAI implementation ───────────────────────────────────────────────


class AzureOpenAIEmbedder:
    """
    Azure OpenAI embeddings backend implementing :class:`EmbedderProtocol`.

    The ``openai`` SDK is an optional dependency, imported lazily on first use
    (``pip install "sdd-pipeline[azure]"``). Azure OpenAI embeddings are already
    ~unit-norm and the vector store uses cosine distance, so no renormalization
    is applied here.
    """

    def __init__(
        self,
        endpoint: str,
        api_key: str,
        deployment: str,
        api_version: str = "2024-10-21",
        batch_size: int = 32,
    ) -> None:
        if not endpoint or not api_key or not deployment:
            raise ValueError(
                "Azure OpenAI embedder requires endpoint, api_key and deployment. "
                "Set PIPELINE_AZURE_OPENAI_ENDPOINT, PIPELINE_AZURE_OPENAI_API_KEY "
                "and PIPELINE_AZURE_OPENAI_DEPLOYMENT."
            )
        self.endpoint = endpoint
        self._api_key = api_key
        self.deployment = deployment
        self.api_version = api_version
        self.batch_size = batch_size
        self._client = None  # lazy
        self._dimension: int | None = None  # cached from first response

    # ── Private ──────────────────────────────────────────────────────────────

    def _get_client(self):
        if self._client is None:
            try:
                # Optional dependency — installed only via the `[azure]` extra.
                from openai import AzureOpenAI  # type: ignore[import-not-found]
            except ImportError as exc:
                raise ImportError(
                    "openai is not installed (required for the Azure embedding provider).\n"
                    'Run: pip install "sdd-pipeline[azure]"'
                ) from exc

            self._client = AzureOpenAI(
                azure_endpoint=self.endpoint,
                api_key=self._api_key,
                api_version=self.api_version,
            )
        return self._client

    # ── Public ────────────────────────────────────────────────────────────────

    def embed(self, texts: list[str]) -> list[list[float]]:
        """Embed *texts* via the Azure OpenAI embeddings endpoint, batched."""
        if not texts:
            return []
        client = self._get_client()
        out: list[list[float]] = []
        for start in range(0, len(texts), self.batch_size):
            batch = texts[start : start + self.batch_size]
            resp = client.embeddings.create(model=self.deployment, input=batch)
            # The API returns rows in input order; sort by .index defensively.
            for row in sorted(resp.data, key=lambda d: d.index):
                out.append(list(row.embedding))
        if out and self._dimension is None:
            self._dimension = len(out[0])
        return out

    def embed_chunks(self, chunks: list[SemanticChunk]) -> list[list[float]]:
        """Embed a list of :class:`SemanticChunk` objects using enriched text."""
        return self.embed([c.to_embed_text() for c in chunks])

    def embed_query(self, query: str) -> list[float]:
        """Embed a single search query string."""
        return self.embed([query])[0]

    @property
    def dimension(self) -> int:
        """Return the embedding vector size (probes the API once if unknown)."""
        if self._dimension is None:
            self.embed(["dimension probe"])
        assert self._dimension is not None
        return self._dimension


# ── Factory & identity ────────────────────────────────────────────────────────


def make_embedder(config: PipelineConfig) -> EmbedderProtocol:
    """Construct the embedder selected by ``config.embedding_provider``."""
    provider = (config.embedding_provider or "local").lower()
    if provider == "local":
        return EmbeddingModel(
            model_name=config.embedding_model,
            batch_size=config.embedding_batch_size,
        )
    if provider == "azure":
        return AzureOpenAIEmbedder(
            endpoint=config.azure_openai_endpoint,
            api_key=config.azure_openai_api_key,
            deployment=config.azure_openai_deployment,
            api_version=config.azure_openai_api_version,
            batch_size=config.embedding_batch_size,
        )
    raise ValueError(f"Unknown embedding_provider {provider!r}; expected 'local' or 'azure'.")


def embedder_identity(config: PipelineConfig) -> tuple[str, str]:
    """Return ``(provider, model_or_deployment)`` for index provenance tagging."""
    provider = (config.embedding_provider or "local").lower()
    if provider == "azure":
        return provider, config.azure_openai_deployment
    return provider, config.embedding_model
