"""
Stage 5: Semantic enrichment.

Adds section_type classification, entity extraction, and semantic tags to
every Section in a DocumentModel.  All logic is pure (no I/O, no network).
An optional LLM path can be layered on top via the enrich_section_with_llm hook.
"""

from __future__ import annotations

import re
from collections.abc import Iterable

from .models import DocumentModel, Section, SectionType

# ── Section-type classification rules ────────────────────────────────────────
# ORDER MATTERS: the first matching rule wins.
# More specific / collision-prone types must appear before general ones.
# NB: matching is plain substring (``kw in title_lower``), so keywords must not
# be substrings of unrelated words — e.g. bare "contra" would match "contract",
# "cons" would match "considerations". Keep them specific.

_SECTION_RULES: dict[SectionType, list[str]] = {
    # "Design Decision" must beat "design" (architecture) → DECISION first.
    # The *chosen* decision / proposed change.
    SectionType.DECISION: [
        "decision",
        "adr",
        "rationale",
        "reasoning",
        "propose",
        "proposal",
        "chosen",
        "why",
    ],
    # Options weighed / rejected approaches. "Options considered", "Considerations".
    SectionType.ALTERNATIVE: [
        "alternative",
        "options considered",
        "option considered",
        "consideration",
        "considered",
        "other options",
        "rejected",
    ],
    # Explicit pro/contra weighing. Keywords kept multi-word to avoid the
    # "contra" ⊂ "contract" / "cons" ⊂ "considerations" collisions.
    SectionType.TRADEOFF: [
        "pro argument",
        "con argument",
        "pros and cons",
        "pros/cons",
        "trade-off",
        "tradeoff",
    ],
    # Resulting impact / downsides / who-is-affected. "migration effort" here
    # so it beats OVERVIEW's "context" ("...in context of...").
    SectionType.CONSEQUENCE: [
        "consequence",
        "downside",
        "drawback",
        "impact",
        "affected",
        "side effect",
        "migration effort",
        "risk",
    ],
    # Acceptance / definition-of-done criteria.
    SectionType.DONE_CRITERIA: [
        "definition of done",
        "defines this",
        "acceptance criteria",
        "success criteria",
    ],
    # "JWT Configuration" must beat "config" (deployment) → SECURITY before it.
    SectionType.SECURITY: [
        "security",
        "auth",
        "authentication",
        "authorization",
        "permission",
        "rbac",
        "token",
        "encryption",
        "tls",
        "certificate",
        "secret",
        "credentials",
        "jwt",
        "oauth",
        "saml",
    ],
    # "Entity Schema" must beat "schema" (api) → DATA_MODEL before API
    SectionType.DATA_MODEL: [
        "data model",
        "entity schema",
        "entity",
        "database",
        "table",
        "field",
        "dto",
        "event schema",
        "message format",
        "payload schema",
    ],
    SectionType.OVERVIEW: [
        "overview",
        "introduction",
        "purpose",
        "summary",
        "background",
        "context",
        "about",
        "scope",
        "goals",
        "objectives",
        "motivation",
        "problem",
    ],
    SectionType.ARCHITECTURE: [
        "architecture",
        "system design",
        "components",
        "structure",
        "high level",
        "high-level",
        "diagram",
        "topology",
        "modules",
    ],
    SectionType.API: [
        "api",
        "interface",
        "endpoint",
        "contract",
        "schema",
        "rest",
        "grpc",
        "openapi",
        "swagger",
        "request",
        "response",
        "payload",
        "routes",
        "operations",
    ],
    SectionType.DEPLOYMENT: [
        "deployment",
        "infrastructure",
        "config",
        "configuration",
        "environment",
        "kubernetes",
        "docker",
        "helm",
        "ci/cd",
        "pipeline",
        "release",
        "rollout",
    ],
}

# Precompiled per-type matchers, in rule order (first match wins). Each pattern
# uses a *leading* word boundary only (``\b`` before the keyword, none after), so
# a keyword matches at a word start — killing suffix/mid-word collisions such as
# "structure" ⊂ "infrastructure" or "api" ⊂ "rapid" — while still matching plural
# / inflected forms like "considerations" ("consideration") or "configuration"
# ("config"). Matching substring would be more permissive; full ``\b…\b`` would
# drop the inflections the rules depend on.
_SECTION_PATTERNS: list[tuple[SectionType, re.Pattern[str]]] = [
    (st, re.compile(r"\b(" + "|".join(re.escape(kw) for kw in keywords) + r")", re.IGNORECASE))
    for st, keywords in _SECTION_RULES.items()
]

# ── Entity extraction patterns ────────────────────────────────────────────────

# Named services / components (PascalCase with a recognisable suffix)
# Uses `*` (zero-or-more) for intermediate segments so that two-word names
# like AuthService and UserService match, not just AuthSomethingService.
_SERVICE_PATTERN = re.compile(
    r"\b([A-Z][a-z]+"  # leading word, e.g. "Auth"
    r"(?:[A-Z][a-z]+)*"  # zero or more middle words
    r"(?:Service|Controller|Manager|Handler|Client|Server|Worker|"
    r"Processor|Repository|Store|Cache|Queue|Bus|Gateway|Proxy|"
    r"Registry|Resolver|Scheduler|Engine|Provider|Factory|"
    r"Adapter|Decorator|Facade|Bridge|Middleware|Filter|Interceptor))\b"
)

# Well-known infrastructure / technology names (fixed set)
_TECH_PATTERN = re.compile(
    r"\b(PostgreSQL|MySQL|MariaDB|MongoDB|Redis|Memcached|"
    r"Elasticsearch|OpenSearch|Kafka|RabbitMQ|Kinesis|Pulsar|"
    r"DynamoDB|Cassandra|S3|GCS|Azure\s*Blob|"
    r"Kubernetes|K8s|Docker|Helm|Terraform|Ansible|"
    r"Nginx|HAProxy|Envoy|Istio|Linkerd)\b",
    re.IGNORECASE,
)

# Protocol / standard acronyms
_PROTOCOL_PATTERN = re.compile(
    r"\b(REST|gRPC|GraphQL|WebSocket|MQTT|AMQP|STOMP|"
    r"JWT|OAuth2?|OIDC|SAML|mTLS|TLS|SSL|HTTPS?)\b"
)

# ── Extra patterns for corpus-wide vocabulary discovery ───────────────────────
# These broaden recall and are used ONLY by scan_corpus() (vocabulary discovery),
# never by extract_entities() (precise per-section tagging).

# ALLCAPS acronyms (3+ chars). Catches domain abbreviations like CQRS, DDD, BFF
# that are absent from the fixed _TECH_ / _PROTOCOL_ sets. Generic noise (HTTP,
# SQL, TODO…) is removed via _ALLCAPS_STOPLIST.
_ALLCAPS_PATTERN = re.compile(r"\b([A-Z][A-Z0-9]{2,})\b")

# Backtick-quoted identifiers as they appear in Markdown. Catches system names,
# config keys, and CLI tokens that don't follow PascalCase conventions:
#   `settlement-engine`, `kube-system`, `x_forwarded_for`
_BACKTICK_PATTERN = re.compile(r"`([A-Za-z][A-Za-z0-9_./-]{2,})`")

# Common ALLCAPS noise excluded from vocabulary — generic English abbreviations,
# terms already normalised by _TECH_ / _PROTOCOL_ patterns, and SQL keywords that
# show up as uppercase tokens inside fenced code blocks.
_ALLCAPS_STOPLIST: frozenset[str] = frozenset(
    {
        # Generic abbreviations / formats
        "HTTP",
        "HTTPS",
        "URL",
        "URI",
        "API",
        "SQL",
        "XML",
        "CSV",
        "JSON",
        "HTML",
        "YAML",
        "PDF",
        "ID",
        "OK",
        "NA",
        "TODO",
        "FIXME",
        "NOTE",
        "NB",
        "FAQ",
        "HR",
        "IT",
        "PM",
        "QA",
        "CI",
        "CD",
        "PR",
        "TBD",
        "WIP",
        "N/A",
        "EOF",
        "EOL",
        "UUID",
        "UTF",
        "TLDR",
        # SQL keywords (uppercase tokens in fenced code) — generic, not entities.
        "SELECT",
        "FROM",
        "WHERE",
        "JOIN",
        "INTO",
        "VALUES",
        "UPDATE",
        "INSERT",
        "DELETE",
        "AND",
        "NOT",
        "SET",
        "GROUP",
        "ORDER",
        "LIMIT",
        "HAVING",
        "NULL",
        "UNION",
        "DISTINCT",
    }
)


def classify_section_type(title: str) -> SectionType:
    """
    Return the best-matching :class:`SectionType` for a section heading.

    The first matching rule in :data:`_SECTION_RULES` wins (order matters).
    Keywords match at a word start (leading word boundary), so they no longer
    bleed into unrelated words (e.g. "structure" ⊄ "infrastructure").
    Returns :attr:`SectionType.CONTENT` when nothing matches.
    """
    for section_type, pattern in _SECTION_PATTERNS:
        if pattern.search(title):
            return section_type
    return SectionType.CONTENT


def _compile_terms(terms: Iterable[str]) -> re.Pattern[str] | None:
    """Compile a case-insensitive, word-bounded alternation of literal *terms*."""
    literals = [re.escape(t.strip()) for t in terms if t and t.strip()]
    if not literals:
        return None
    # Longest first so multi-word terms win over their prefixes.
    literals.sort(key=len, reverse=True)
    return re.compile(r"\b(" + "|".join(literals) + r")\b", re.IGNORECASE)


def extract_entities(text: str, extra_terms: Iterable[str] | None = None) -> list[str]:
    """Extract named entities (services, tech, protocols) from plain text.

    *extra_terms* lets a project inject its own domain vocabulary (e.g.
    ``["KPO", "triggerer", "XCom"]``) without editing this module; matches are
    returned in their canonical (supplied) spelling.
    """
    found: set[str] = set()
    for match in _SERVICE_PATTERN.finditer(text):
        found.add(match.group(1))
    for match in _TECH_PATTERN.finditer(text):
        # Normalise case for infrastructure names
        found.add(match.group(1).replace(" ", ""))
    for match in _PROTOCOL_PATTERN.finditer(text):
        found.add(match.group(1))
    if extra_terms:
        # Map each lower-cased hit back to the supplied spelling so output is
        # stable regardless of how the term is cased in the text.
        canonical = {t.strip().lower(): t.strip() for t in extra_terms if t and t.strip()}
        pattern = _compile_terms(canonical)
        if pattern is not None:
            for match in pattern.finditer(text):
                found.add(canonical.get(match.group(1).lower(), match.group(1)))
    return sorted(found)


def extract_tags(
    title: str,
    section_type: SectionType,
    blocks_text: str,
) -> list[str]:
    """Generate semantic tags for a section from its type, title, and content."""
    tags: list[str] = [section_type.value]

    # Programming languages found in fenced code blocks. The fence may be
    # indented (code nested in a list) or prefixed by blockquote markers
    # (``> ``), so allow leading whitespace / one-or-more ``>`` before it.
    for lang in re.findall(r"(?m)^[ \t]*(?:>[ \t]*)*```(\w+)", blocks_text):
        tag = f"lang:{lang.lower()}"
        if tag not in tags:
            tags.append(tag)

    return tags


def enrich_section(section: Section, entity_terms: Iterable[str] | None = None) -> None:
    """Mutate *section* in place, adding section_type, entities, and tags."""
    section.section_type = classify_section_type(section.title)

    all_text = section.title + "\n" + "\n".join(b.text for b in section.blocks)
    section.entities = extract_entities(all_text, entity_terms)
    section.tags = extract_tags(section.title, section.section_type, all_text)

    for sub in section.subsections:
        enrich_section(sub, entity_terms)


def enrich_document(doc: DocumentModel, entity_terms: Iterable[str] | None = None) -> DocumentModel:
    """
    Apply semantic enrichment to all sections of *doc* and return it.

    *entity_terms* is an optional project vocabulary folded into entity
    extraction (see :func:`extract_entities`). The mutation is in-place for
    performance; the same object is returned to allow chaining:
    ``doc = enrich_document(build_structural_model(...))``.
    """
    for section in doc.root_sections:
        enrich_section(section, entity_terms)
    return doc


# ── Cross-corpus vocabulary discovery ─────────────────────────────────────────
# A read-only first pass over the whole document set, run *before* enrichment, so
# a term seen in one document is recognised as an entity in every document. The
# resulting list is fed back as the ``entity_terms`` of :func:`enrich_document`.


def _collect_raw_terms(text: str) -> set[str]:
    """Run *all* extraction patterns over *text* and return every candidate.

    A superset of :func:`extract_entities` — it adds the discovery-only patterns
    (``_ALLCAPS_PATTERN``, ``_BACKTICK_PATTERN``). Results are unfiltered; length
    and stoplist filtering happen in :func:`scan_corpus`.
    """
    found: set[str] = set()
    for match in _SERVICE_PATTERN.finditer(text):
        found.add(match.group(1))
    for match in _TECH_PATTERN.finditer(text):
        found.add(match.group(1).replace(" ", ""))
    for match in _PROTOCOL_PATTERN.finditer(text):
        found.add(match.group(1))
    for match in _ALLCAPS_PATTERN.finditer(text):
        term = match.group(1)
        if term not in _ALLCAPS_STOPLIST:
            found.add(term)
    for match in _BACKTICK_PATTERN.finditer(text):
        found.add(match.group(1))
    return found


def _collect_section_terms(section: Section, found: set[str]) -> None:
    """Recursive read-only walk; accumulate raw candidates into *found*.

    Touches no Section attribute — safe to call before :func:`enrich_document`.
    """
    text = section.title + "\n" + "\n".join(b.text for b in section.blocks)
    found.update(_collect_raw_terms(text))
    for sub in section.subsections:
        _collect_section_terms(sub, found)


def scan_corpus(
    docs: Iterable[DocumentModel],
    *,
    seed_terms: Iterable[str] | None = None,
    min_length: int = 3,
) -> list[str]:
    """Discover an entity vocabulary across *docs* (read-only).

    Performs a read-only pass over every section of every document and returns a
    deduplicated, sorted list of entity candidates — a drop-in for the
    ``entity_terms`` parameter of :func:`enrich_document`. ::

        vocabulary = scan_corpus(all_docs, seed_terms=prior_vocabulary)
        for doc in all_docs:
            enrich_document(doc, entity_terms=vocabulary)

    Why two passes? :func:`extract_entities` only uses the terms handed to it, so
    a term in document A is not applied to document B. Scanning the whole corpus
    first makes every term visible everywhere during enrichment.

    Args:
        docs:        DocumentModel objects (after parsing, before enrichment).
        seed_terms:  Vocabulary from a previous run, merged in so coverage
                     accumulates over time.
        min_length:  Discard candidates shorter than this (default 3) to reduce
                     single-letter and two-char acronym noise.
    """
    found: set[str] = set()
    if seed_terms:
        found.update(t.strip() for t in seed_terms if t and t.strip())
    for doc in docs:
        for section in doc.root_sections:
            _collect_section_terms(section, found)
    return sorted(t for t in found if len(t) >= min_length)
