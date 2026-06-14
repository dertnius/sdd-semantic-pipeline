"""
Pipeline configuration.
All values can be overridden via environment variables (prefix: PIPELINE_) or a .env file.
"""

from __future__ import annotations

from pydantic import Field

try:
    from pydantic_settings import BaseSettings, SettingsConfigDict

    class PipelineConfig(BaseSettings):
        """Runtime configuration for the SDD semantic pipeline."""

        # ── Pandoc ────────────────────────────────────────────────────────────
        pandoc_from_format: str = Field(
            default="gfm",
            description="Input format passed to pandoc --from (gfm, markdown, commonmark).",
        )

        # ── Embedding ─────────────────────────────────────────────────────────
        embedding_model: str = Field(
            default="BAAI/bge-large-en-v1.5",
            description="sentence-transformers model name or HuggingFace model ID.",
        )
        embedding_batch_size: int = Field(default=32, description="Encoding batch size.")

        # ── Embedding provider ────────────────────────────────────────────────
        embedding_provider: str = Field(
            default="local",
            description="Embedding backend: 'local' (sentence-transformers) or 'azure'.",
        )
        azure_openai_endpoint: str = Field(
            default="",
            description="Azure OpenAI endpoint, e.g. https://<resource>.openai.azure.com/.",
        )
        azure_openai_api_key: str = Field(
            default="",
            description="Azure OpenAI API key. SECRET — set via PIPELINE_AZURE_OPENAI_API_KEY env.",
        )
        azure_openai_deployment: str = Field(
            default="",
            description="Azure OpenAI embeddings deployment name (used as the model arg).",
        )
        azure_openai_api_version: str = Field(
            default="2024-10-21",
            description="Azure OpenAI API version for the embeddings endpoint.",
        )

        # ── Chunking ──────────────────────────────────────────────────────────
        max_chunk_chars: int = Field(
            default=2000,
            description="Maximum characters per semantic chunk before splitting.",
        )
        chunk_merge_prose: bool = Field(
            default=False,
            description="Pack a section's prose blocks into one chunk (code/tables stay separate).",
        )
        chunk_merge_definitions: bool = Field(
            default=False,
            description="Pack a section's prose AND code into one chunk (tables stay separate); "
            "co-locates an instruction's explanation with its syntax. Overrides merge_prose.",
        )
        embed_char_budget: int = Field(
            default=1800,
            description="Target max chars for the rendered embed_text (header + content). "
            "Conservative for a 512-token model so vectors are not silently truncated.",
        )

        # ── Chunk hygiene gate (Arm 1) ────────────────────────────────────────
        chunk_gate: bool = Field(
            default=True,
            description="Run the chunk-level hygiene invariant during indexing. A "
            "*poisoned* chunk (markup/macro residue, over-hard-cap embed text, or empty) "
            "blocks the whole file from the index. Disable to index without the gate.",
        )
        embed_char_hard_cap: int = Field(
            default=2048,
            description="Hard ceiling (chars) for the rendered embed_text. Above this the "
            "model would silently truncate the vector, so the chunk gate treats it as "
            "poison (vs embed_char_budget, the soft target whose breach is only a warning).",
        )

        # ── Converter confidence gate (Arm 2) ─────────────────────────────────
        convert_quarantine: bool = Field(
            default=True,
            description="When the converter's own signals say it likely mangled a page "
            "(no recognised content container, or many leftover storage tags), mark the "
            "file quarantined in the convert report and exit non-zero, instead of letting "
            "a low-confidence conversion enter the corpus silently.",
        )
        convert_max_unrecognized: int = Field(
            default=8,
            description="Quarantine threshold: a converted file is quarantined when its "
            "dropped/unrecognised-construct count exceeds this (a root-container fallback "
            "always quarantines). Calibrate from a run over your known-good corpus.",
        )

        # ── Enrichment ────────────────────────────────────────────────────────
        entity_terms: list[str] = Field(
            default_factory=list,
            description="Project domain vocabulary folded into entity extraction "
            "(e.g. KubernetesPodOperator, triggerer, XCom). PIPELINE_ENTITY_TERMS "
            "accepts a JSON array.",
        )
        entity_vocab_path: str = Field(
            default="",
            description="Path to a JSON vocabulary file. When set (PIPELINE_ENTITY_VOCAB_PATH), "
            "`index` runs a two-pass cross-corpus scan: discover entity terms across all "
            "docs, persist them here (accumulating across runs), then enrich every doc with "
            "the full vocabulary. Empty disables the scan.",
        )
        inventory_enrichment: bool = Field(
            default=True,
            description="Route structural (table) + prose entity records into "
            "depends_on/exposes/metadata and fold them into embed text. Disable for "
            "legacy enrichment only (section_type/entities/tags).",
        )

        # ── Vector store ──────────────────────────────────────────────────────
        vector_store_backend: str = Field(
            default="memory",
            description="Vector store backend: 'memory' (langchain-core InMemoryVectorStore, "
            "persisted as JSON) or 'chroma' (requires pip install '.[chroma]').",
        )
        chroma_persist_dir: str = Field(
            default="./data/chroma",
            description="Directory where the vector index persists (Chroma files, or "
            "<collection>.json for the memory backend).",
        )
        collection_name: str = Field(
            default="sdd_docs",
            description="Vector store collection name.",
        )

        # ── Hybrid retrieval ──────────────────────────────────────────────────
        hybrid_search: bool = Field(
            default=False,
            description="Fuse dense (vector) and lexical (BM25) rankings via RRF.",
        )
        hybrid_candidate_pool: int = Field(
            default=50,
            description="Per-scorer candidate depth fused before taking top-k.",
        )
        rrf_k: int = Field(
            default=60,
            description="Reciprocal Rank Fusion constant (higher = flatter weighting).",
        )

        model_config = SettingsConfigDict(
            env_prefix="PIPELINE_",
            env_file=".env",
            env_file_encoding="utf-8",
            extra="ignore",
        )

except ImportError:
    # Fallback for pydantic v1 or missing pydantic-settings
    from pydantic import BaseSettings  # type: ignore[assignment, no-redef]

    class PipelineConfig(BaseSettings):  # type: ignore[no-redef]
        pandoc_from_format: str = "gfm"
        embedding_model: str = "BAAI/bge-large-en-v1.5"
        embedding_batch_size: int = 32
        embedding_provider: str = "local"
        azure_openai_endpoint: str = ""
        azure_openai_api_key: str = ""
        azure_openai_deployment: str = ""
        azure_openai_api_version: str = "2024-10-21"
        max_chunk_chars: int = 2000
        chunk_merge_prose: bool = False
        chunk_merge_definitions: bool = False
        embed_char_budget: int = 1800
        chunk_gate: bool = True
        embed_char_hard_cap: int = 2048
        convert_quarantine: bool = True
        convert_max_unrecognized: int = 8
        entity_terms: list[str] = []
        entity_vocab_path: str = ""
        inventory_enrichment: bool = True
        vector_store_backend: str = "memory"
        chroma_persist_dir: str = "./data/chroma"
        collection_name: str = "sdd_docs"
        hybrid_search: bool = False
        hybrid_candidate_pool: int = 50
        rrf_k: int = 60

        class Config:
            env_prefix = "PIPELINE_"
            env_file = ".env"
