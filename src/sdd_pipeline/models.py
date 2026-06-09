"""
Core data models for the SDD semantic pipeline.
All types are dataclasses; no external dependencies.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Literal

# Languages trusted enough to embed as a `lang:` token. A source's
# syntaxhighlighter brush is often wrong for DSLs, so unknown labels are dropped
# from the vector (the full tag is still kept in metadata for filtering).
_EMBED_LANGS = frozenset(
    {
        "python",
        "sql",
        "json",
        "yaml",
        "yml",
        "bash",
        "shell",
        "sh",
        "javascript",
        "typescript",
        "java",
        "go",
        "rust",
        "c",
        "cpp",
        "csharp",
        "ruby",
        "php",
        "xml",
        "html",
        "css",
        "kotlin",
        "scala",
        "toml",
        "ini",
        "dockerfile",
        "groovy",
        "perl",
        "powershell",
        "swift",
        "r",
    }
)


def _summarize_table_for_embed(content: str) -> str:
    """Compact a rendered pipe table for embedding.

    Keeps the header row (+ separator) and replaces the data rows with a count,
    so high-entropy cell values (IDs, codes) don't dominate the vector. The full
    table stays in :attr:`SemanticChunk.content` for display/export.
    """
    lines = [ln for ln in content.splitlines() if ln.strip()]
    if not lines:
        return content
    # A GitHub pipe table is: header | separator (---) | data rows.
    sep_idx = next(
        (i for i, ln in enumerate(lines) if set(ln.replace("|", "").strip()) <= {"-", " ", ":"}),
        None,
    )
    if sep_idx is None:
        return content
    head = lines[: sep_idx + 1]
    n_rows = len(lines) - (sep_idx + 1)
    return "\n".join(head) + f"\n(table, {n_rows} data rows)"


class ContentType(StrEnum):
    PARAGRAPH = "paragraph"
    CODE = "code"
    TABLE = "table"
    LIST = "list"
    BLOCKQUOTE = "blockquote"


class SectionType(StrEnum):
    OVERVIEW = "overview"
    ARCHITECTURE = "architecture"
    API = "api"
    DECISION = "decision"
    # ADR/AIP decision-record elements — let retrieval distinguish the chosen
    # decision from the alternatives weighed, their trade-offs, the resulting
    # consequences, and the acceptance criteria.
    ALTERNATIVE = "alternative"
    TRADEOFF = "tradeoff"
    CONSEQUENCE = "consequence"
    DONE_CRITERIA = "done_criteria"
    DEPLOYMENT = "deployment"
    DATA_MODEL = "data_model"
    SECURITY = "security"
    CONTENT = "content"


@dataclass
class ContentBlock:
    """A single typed block of content within a section."""

    block_id: str
    content_type: ContentType
    text: str
    language: str | None = None  # populated for CodeBlock
    raw: dict[str, Any] | None = field(default=None, repr=False)


@dataclass
class Section:
    """A document section corresponding to a heading hierarchy node."""

    level: int  # 1 = H1, 2 = H2, …
    title: str
    section_id: str
    breadcrumb: list[str]  # ["Service Design", "Auth", "Token Flow"]
    blocks: list[ContentBlock] = field(default_factory=list)
    subsections: list[Section] = field(default_factory=list)
    section_type: SectionType = SectionType.CONTENT
    entities: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    depends_on: list[str] = field(default_factory=list)
    exposes: list[str] = field(default_factory=list)


@dataclass
class DocumentMetadata:
    """Metadata extracted from YAML frontmatter."""

    title: str
    space: str = ""
    url: str = ""
    labels: list[str] = field(default_factory=list)
    author: str = ""
    last_modified: str = ""
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class DocumentModel:
    """Structural representation of a parsed Confluence markdown page."""

    doc_id: str
    metadata: DocumentMetadata
    root_sections: list[Section] = field(default_factory=list)
    source_path: str = ""

    def iter_sections(self) -> list[Section]:
        """Flatten all sections (BFS order)."""
        result: list[Section] = []
        queue = list(self.root_sections)
        while queue:
            section = queue.pop(0)
            result.append(section)
            queue.extend(section.subsections)
        return result


@dataclass
class SemanticChunk:
    """
    A context-enriched unit ready for embedding and indexing.

    Each chunk corresponds to one or more ContentBlocks from a Section,
    carrying the full breadcrumb and semantic metadata as first-class fields.
    """

    chunk_id: str
    doc_id: str
    breadcrumb: list[str]
    content: str
    content_type: ContentType
    language: str | None
    section_type: SectionType
    entities: list[str]
    tags: list[str]
    depends_on: list[str]
    exposes: list[str]
    space: str
    labels: list[str]
    # Document-level provenance, carried onto every chunk so an exported record
    # is citable on its own (the doc_id alone is an opaque hash).
    title: str = ""
    source_url: str = ""

    def to_embed_text(self) -> str:
        """
        Build enriched text for embedding.

        Prepends structural context (section type + breadcrumb) and folds in the
        computed keywords/tags so the semantic signal reaches the vector — while
        keeping out dead or misleading tokens: the null ``content`` type, tags
        that merely echo the section type, keywords that merely repeat the
        breadcrumb, and untrusted ``lang:`` labels. Data tables are summarized so
        high-entropy cells don't dominate the vector.
        """
        crumb = " > ".join(self.breadcrumb)
        # Omit the bracket prefix for the null CONTENT type — it carries no signal.
        parts: list[str] = []
        if self.section_type != SectionType.CONTENT:
            parts.append(
                f"[{self.section_type.value}] {crumb}" if crumb else f"[{self.section_type.value}]"
            )
        elif crumb:
            parts.append(crumb)

        # Keywords minus any that just repeat a breadcrumb token.
        crumb_tokens = {b.strip().rstrip(":").lower() for b in self.breadcrumb}
        keywords = [e for e in self.entities if e.lower() not in crumb_tokens]
        if keywords:
            parts.append("keywords: " + ", ".join(keywords))

        # Tags minus the section-type echo and untrusted lang labels.
        embed_tags: list[str] = []
        for t in self.tags:
            if t == self.section_type.value:
                continue
            if t.startswith("lang:") and t[5:].lower() not in _EMBED_LANGS:
                continue
            embed_tags.append(t)
        if embed_tags:
            parts.append("tags: " + ", ".join(embed_tags))

        # Surface the code language unless a `lang:` tag already carries it —
        # only when it is a trusted language.
        if (
            self.content_type == ContentType.CODE
            and self.language
            and self.language.lower() in _EMBED_LANGS
            and f"lang:{self.language}" not in self.tags
        ):
            parts.append(f"lang:{self.language}")

        header = " | ".join(parts)
        body = (
            _summarize_table_for_embed(self.content)
            if self.content_type == ContentType.TABLE
            else self.content
        )
        return f"{header}\n\n{body}" if header else body

    def to_metadata(self) -> dict[str, str | int | float | bool]:
        """
        Serialize to a ChromaDB-compatible metadata dict.
        All values must be scalar (str | int | float | bool).
        """
        return {
            "doc_id": self.doc_id,
            "breadcrumb": " > ".join(self.breadcrumb),
            "content_type": self.content_type.value,
            "language": self.language or "",
            "section_type": self.section_type.value,
            "entities": json.dumps(self.entities),
            "tags": json.dumps(self.tags),
            "depends_on": json.dumps(self.depends_on),
            "exposes": json.dumps(self.exposes),
            "space": self.space,
            "labels": json.dumps(self.labels),
            "title": self.title,
            "source_url": self.source_url,
        }

    def to_dict(self) -> dict[str, Any]:
        """
        Lossless, JSON-serializable view for exporting to other pipelines.

        Unlike :meth:`to_metadata` (Chroma-specific: scalar-only, JSON-encoded
        lists, flattened breadcrumb), this keeps lists as real arrays and
        ``language`` as ``null`` when unset, and adds ``embed_text`` — the exact
        string this chunk would be embedded with.
        """
        return {
            "chunk_id": self.chunk_id,
            "doc_id": self.doc_id,
            "breadcrumb": list(self.breadcrumb),
            "content": self.content,
            "content_type": self.content_type.value,
            "language": self.language,
            "section_type": self.section_type.value,
            "entities": list(self.entities),
            "tags": list(self.tags),
            "depends_on": list(self.depends_on),
            "exposes": list(self.exposes),
            "space": self.space,
            "labels": list(self.labels),
            "title": self.title,
            "source_url": self.source_url,
            "embed_text": self.to_embed_text(),
        }


# ── Entity extraction contract (inventory-driven enrichment) ───────────────────

# Extraction source, ordered by trust. Used to break ties in deduplication.
EntitySource = Literal[
    "table_cell",  # 1.0 — a cell in a structured template table
    "allcaps_regex",  # 0.9 — ACME_SERVICE style token
    "backtick_regex",  # 0.8 — `code`-fenced token
    "noun_chunk",  # 0.5 — spaCy multi-word noun chunk
    "prose",  # generic prose mention
]


@dataclass(frozen=True)
class EntityRecord:
    """One extracted entity, tagged with the template field it came from.

    ``field`` is a normalised taxonomy field/column name (e.g. ``related
    component``); enrichment routes it to depends_on/exposes/metadata. ``text``
    is the raw value; ``canonical`` is its canonical form (defaults to ``text``).
    """

    text: str
    field: str
    source: EntitySource
    confidence: float
    section_id: str
    canonical: str = ""

    def __post_init__(self) -> None:
        if not self.canonical:
            object.__setattr__(self, "canonical", self.text)


# Inventory of extracted records, keyed by Section.section_id.
EntityInventory = dict[str, list[EntityRecord]]
