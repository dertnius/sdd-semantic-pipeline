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

        # ── Language ──────────────────────────────────────────────────────────
        language: str = Field(
            default="en",
            description="Document language for enrichment rules: en|de|fr|it, or 'auto' "
            "to detect per document (auto needs the [lang] extra). Unsupported codes fall "
            "back to English.",
        )
        lexical_only: bool = Field(
            default=False,
            description="Model-free search: skip dense embedding and rank by BM25 lexical "
            "score only. No embedding model is loaded — works for every language.",
        )
        lexical_stemming: bool = Field(
            default=False,
            description="Apply snowball stemming (en/de/fr/it) during BM25 tokenization for "
            "better recall. Needs the [stem] extra; only safe on a single-language index.",
        )

        # ── Downloader (optional SiteMinder-protected ingestion) ──────────────
        # Used only by the `download` command. Credentials are SECRETS — set via env
        # (PIPELINE_DOWNLOAD_*), never CLI args. The deterministic core never reads these.
        download_auth: str = Field(
            default="cookie",
            description="SiteMinder auth strategy: cookie (pre-issued SMSESSION, primary) | "
            "form (headless username/password login) | bearer (token) | none (plain GET).",
        )
        download_cookie: str = Field(
            default="",
            description="SECRET: pre-issued SMSESSION cookie value (PIPELINE_DOWNLOAD_COOKIE).",
        )
        download_cookie_name: str = Field(
            default="SMSESSION", description="Session cookie name (SiteMinder default SMSESSION)."
        )
        download_bearer: str = Field(
            default="",
            description="SECRET: bearer token for download_auth=bearer (PIPELINE_DOWNLOAD_BEARER).",
        )
        download_login_url: str = Field(
            default="", description="SiteMinder form-login POST URL (download_auth=form)."
        )
        download_username: str = Field(
            default="", description="Service-account username (download_auth=form)."
        )
        download_password: str = Field(
            default="", description="SECRET: service-account password (PIPELINE_DOWNLOAD_PASSWORD)."
        )
        download_user_field: str = Field(
            default="USER", description="Login form field name carrying the username."
        )
        download_pass_field: str = Field(
            default="PASSWORD", description="Login form field name carrying the password."
        )
        download_timeout: int = Field(
            default=60, description="Per-request download timeout in seconds."
        )
        download_verify_tls: bool = Field(
            default=True, description="Verify TLS certs; --insecure sets this false."
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

        # ── Document profile routing (advisory) ───────────────────────────────
        doc_profile_enabled: bool = Field(
            default=False,
            description="Auto-detect a coarse document profile (technical/prose/mixed) and "
            "use it to pick a default chunk merge strategy when the user set none "
            "(technical→merge_definitions, prose→merge_prose, mixed→no merge). Off by "
            "default so output is unchanged; the profile is surfaced on metadata.extra.",
        )
        doc_profile_code_ratio: float = Field(
            default=0.5,
            description="Code-char fraction at/above which a document is profiled technical.",
        )
        doc_profile_table_ratio: float = Field(
            default=0.4,
            description="Table-char fraction at/above which a document is profiled technical.",
        )
        prose_keyphrases: bool = Field(
            default=True,
            description="Merge deterministic RAKE keyphrases into the embed keywords of "
            "prose-genre chunks (glossary/faq/howto/policy/narrative), enriching the vector "
            "for non-technical content. Technical/code sections are untouched.",
        )
        chunk_overlap_sentences: int = Field(
            default=0,
            description="When > 0, a prose block that splits carries its trailing N sentences "
            "into the next chunk so a boundary-straddling answer survives in at least one "
            "vector. Code and tables never overlap. 0 (default) keeps chunks disjoint.",
        )
        prose_ner: bool = Field(
            default=True,
            description="Extract named entities (person/org/place/date) from prose via the "
            "optional, import-guarded spaCy layer into ner:* metadata facets (display/filter "
            "only — never the embed vector). Inert when spaCy/model is not installed.",
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
            default="./outbox/index",
            description="Directory where the vector index persists (Chroma files, or "
            "<collection>.json for the memory backend). Lives under the outbox.",
        )
        collection_name: str = Field(
            default="sdd_docs",
            description="Vector store collection name.",
        )

        # ── Workspace contract (inbox / outbox) ───────────────────────────────
        inbox_dir: str = Field(
            default="./inbox",
            description="Root for all pipeline INPUT files (subfolders allowed). With "
            "enforce_workspace on, every input path must resolve under here.",
        )
        outbox_dir: str = Field(
            default="./outbox",
            description="Root for all pipeline OUTPUTS — index, md, chunks, reports, "
            "vocab, taxonomy, dump (subfolders allowed). With enforce_workspace on, "
            "every output path must resolve under here.",
        )
        enforce_workspace: bool = Field(
            default=True,
            description="Enforce the inbox/outbox contract: reject input paths not under "
            "inbox_dir and output paths not under outbox_dir. Set false (e.g. in tests or "
            "ad-hoc runs) to skip all containment checks.",
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

        # ── Shell tooling (PowerShell 7 discovery) ────────────────────────────
        pwsh_path: str = Field(
            default="",
            description="Explicit path to a PowerShell 7 (pwsh) executable. When set "
            "(PIPELINE_PWSH_PATH) the shell resolver commits to it verbatim (sticky) "
            "instead of auto-discovering pwsh — non-intrusive, never edits PATH. "
            "Empty = auto-discover. Surfaced by `check`; consumed by `pwsh-path`.",
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
        language: str = "en"
        lexical_only: bool = False
        lexical_stemming: bool = False
        download_auth: str = "cookie"
        download_cookie: str = ""
        download_cookie_name: str = "SMSESSION"
        download_bearer: str = ""
        download_login_url: str = ""
        download_username: str = ""
        download_password: str = ""
        download_user_field: str = "USER"
        download_pass_field: str = "PASSWORD"
        download_timeout: int = 60
        download_verify_tls: bool = True
        max_chunk_chars: int = 2000
        chunk_merge_prose: bool = False
        chunk_merge_definitions: bool = False
        embed_char_budget: int = 1800
        doc_profile_enabled: bool = False
        doc_profile_code_ratio: float = 0.5
        doc_profile_table_ratio: float = 0.4
        prose_keyphrases: bool = True
        chunk_overlap_sentences: int = 0
        prose_ner: bool = True
        chunk_gate: bool = True
        embed_char_hard_cap: int = 2048
        convert_quarantine: bool = True
        convert_max_unrecognized: int = 8
        entity_terms: list[str] = []
        entity_vocab_path: str = ""
        inventory_enrichment: bool = True
        vector_store_backend: str = "memory"
        chroma_persist_dir: str = "./outbox/index"
        collection_name: str = "sdd_docs"
        inbox_dir: str = "./inbox"
        outbox_dir: str = "./outbox"
        enforce_workspace: bool = True
        hybrid_search: bool = False
        hybrid_candidate_pool: int = 50
        rrf_k: int = 60
        pwsh_path: str = ""

        class Config:
            env_prefix = "PIPELINE_"
            env_file = ".env"
