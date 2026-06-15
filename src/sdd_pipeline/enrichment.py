"""
Stage 5: Semantic enrichment.

Adds section_type classification, entity extraction, and semantic tags to
every Section in a DocumentModel.  All logic is pure (no I/O, no network).
An optional LLM path can be layered on top via the enrich_section_with_llm hook.
"""

from __future__ import annotations

import re
from collections.abc import Iterable

from .direction import Direction, load_field_directions, resolve_direction
from .models import (
    ContentType,
    DocumentModel,
    EntityInventory,
    EntityRecord,
    Genre,
    Section,
    SectionType,
)
from .reconcile import reconcile

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

# HTTP API endpoints: an uppercase method followed by a leading-slash path
# (``GET /v1/users``, ``POST /api/orders/{id}``). The method + leading slash make
# this tight enough not to fire on ordinary prose, so it is safe in the always-on
# extractor; the endpoint becomes a first-class keyword for API docs.
_ENDPOINT_PATTERN = re.compile(
    r"\b(GET|POST|PUT|PATCH|DELETE|HEAD|OPTIONS)\s+(/[A-Za-z0-9_/{}.:\-]*)"
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

# Fenced code blocks (``` or ~~~). Blanked before the corpus scan mines a section,
# so ALLCAPS tokens inside code don't surface as entities. Inline ``code`` (single
# backticks) is intentionally left intact — it is a deliberate discovery signal.
_FENCED = re.compile(r"```[\s\S]*?```|~~~[\s\S]*?~~~")

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


# ── Genre classification (prose shape; orthogonal to SectionType) ──────────────
# A section's genre answers "what prose shape?" — glossary / faq / howto / policy /
# narrative — independently of its technical SectionType. Strategy: a prose-ness
# gate (code/table-dominant → GENERAL), then body-shape detectors in priority
# order, with the title used only as a confirmer/promoter. On a title-vs-body
# conflict the body wins (prose headings are often generic); a prose section that
# matches no detector falls back to NARRATIVE.

# Block types that count as prose for the prose-ness gate.
_PROSE_BLOCK_TYPES = frozenset(
    {ContentType.PARAGRAPH, ContentType.LIST, ContentType.BLOCKQUOTE, ContentType.DEFINITION}
)
_PROSE_RATIO_MIN = 0.5  # below this fraction of prose chars → GENERAL (code/table doc)
_GLOSSARY_DEF_RATIO = 0.5  # definition blocks ≥ this fraction of prose → glossary
_FAQ_QUESTION_MIN = 2  # this many question paragraphs → faq
_POLICY_MODAL_MIN = 2  # this many strong obligation modals → policy

# Strong obligation modals (governance prose). "should" is intentionally excluded
# — too weak/common in ordinary explanation to signal a policy.
_MODAL_RE = re.compile(
    r"\b(?:must(?:\s+not)?|shall(?:\s+not)?|may\s+not|required|prohibited|mandatory|forbidden)\b",
    re.IGNORECASE,
)
# Common imperative step verbs that open how-to list items.
_IMPERATIVE_VERBS = frozenset(
    {
        "install",
        "run",
        "click",
        "open",
        "create",
        "set",
        "configure",
        "add",
        "remove",
        "select",
        "enter",
        "navigate",
        "choose",
        "download",
        "save",
        "deploy",
        "build",
        "start",
        "stop",
        "restart",
        "copy",
        "paste",
        "update",
        "verify",
        "check",
        "ensure",
        "define",
        "call",
        "import",
        "export",
        "execute",
        "launch",
        "type",
        "press",
        "go",
        "visit",
        "enable",
        "disable",
        "apply",
        "edit",
        "delete",
        "push",
        "pull",
        "commit",
        "clone",
        "login",
        "register",
        "upload",
        "submit",
        "review",
        "confirm",
        "repeat",
        "close",
        "find",
        "replace",
    }
)
# An ordered-list item line ("1. text") as serialized by structural._serialize_list.
_ORDERED_ITEM_RE = re.compile(r"^\s*\d+\.\s+(.*)$")

# Title keyword → genre (leading word boundary, mirroring _SECTION_RULES).
_GENRE_TITLE_RULES: dict[Genre, list[str]] = {
    Genre.GLOSSARY: ["glossary", "definitions", "terminology", "terms", "nomenclature"],
    Genre.FAQ: ["faq", "frequently asked", "q&a", "questions and answers"],
    Genre.HOWTO: [
        "how to",
        "how-to",
        "howto",
        "tutorial",
        "walkthrough",
        "step-by-step",
        "step by step",
        "getting started",
        "installation",
        "setup",
        "procedure",
        "runbook",
    ],
    Genre.POLICY: [
        "policy",
        "policies",
        "guideline",
        "guidelines",
        "compliance",
        "code of conduct",
        "terms of service",
        "acceptable use",
    ],
}
_GENRE_TITLE_PATTERNS: list[tuple[Genre, re.Pattern[str]]] = [
    (g, re.compile(r"\b(" + "|".join(re.escape(k) for k in kws) + r")", re.IGNORECASE))
    for g, kws in _GENRE_TITLE_RULES.items()
]


def _genre_from_title(title: str) -> Genre | None:
    """First title-keyword genre match (confirmer/promoter), or None."""
    for genre, pattern in _GENRE_TITLE_PATTERNS:
        if pattern.search(title):
            return genre
    return None


def _is_glossary(blocks: list, prose_chars: int) -> bool:
    def_chars = sum(len(b.text) for b in blocks if b.content_type == ContentType.DEFINITION)
    return prose_chars > 0 and def_chars / prose_chars >= _GLOSSARY_DEF_RATIO


def _is_faq(blocks: list) -> bool:
    questions = sum(
        1
        for b in blocks
        if b.content_type == ContentType.PARAGRAPH and b.text.strip().endswith("?")
    )
    return questions >= _FAQ_QUESTION_MIN


def _is_howto(blocks: list) -> bool:
    """An ordered list with ≥2 items that lead with an imperative verb."""
    for b in blocks:
        if b.content_type != ContentType.LIST:
            continue
        total = imperative = 0
        for line in b.text.splitlines():
            m = _ORDERED_ITEM_RE.match(line)
            if not m:
                continue
            total += 1
            words = m.group(1).strip().lower().split()
            first = words[0].strip(".,:;)") if words else ""
            if first in _IMPERATIVE_VERBS:
                imperative += 1
        if total >= 2 and imperative >= 2:
            return True
    return False


def classify_genre(section: Section) -> Genre:
    """Return the prose :class:`Genre` of *section* (see module comment above).

    Orthogonal to :func:`classify_section_type`; both run during enrichment.
    """
    blocks = section.blocks
    title_genre = _genre_from_title(section.title)
    if not blocks:
        return title_genre or Genre.GENERAL

    total_chars = sum(len(b.text) for b in blocks)
    prose_chars = sum(len(b.text) for b in blocks if b.content_type in _PROSE_BLOCK_TYPES)
    if total_chars == 0 or prose_chars / total_chars < _PROSE_RATIO_MIN:
        # Code/table-dominant: the prose axis does not apply. A title keyword can
        # still promote (e.g. a "Glossary" heading over a term *table*).
        return title_genre or Genre.GENERAL

    prose_text = "\n".join(b.text for b in blocks if b.content_type in _PROSE_BLOCK_TYPES)

    # Body-shape detectors, first match wins (glossary → faq → howto → policy).
    if _is_glossary(blocks, prose_chars):
        body_genre: Genre | None = Genre.GLOSSARY
    elif _is_faq(blocks):
        body_genre = Genre.FAQ
    elif _is_howto(blocks):
        body_genre = Genre.HOWTO
    elif len(_MODAL_RE.findall(prose_text)) >= _POLICY_MODAL_MIN:
        body_genre = Genre.POLICY
    else:
        body_genre = None

    # Body wins on conflict; title promotes when the body is silent; else narrative.
    if body_genre is not None:
        return body_genre
    if title_genre is not None:
        return title_genre
    return Genre.NARRATIVE


# ── Document profile (technical vs prose) — advisory routing signal ────────────
# A coarse, model-free label computed on the parsed model *before* enrichment.
# It is advisory: the orchestrator uses it to pick a default chunk merge strategy
# when the user set none; it never overrides an explicit choice and never feeds
# the deterministic core. Pure function — the pipeline does the surfacing/mutation.
_PROFILE_PROSE_CODE_MAX = 0.05
_PROFILE_PROSE_TABLE_MAX = 0.10


def classify_document(
    doc: DocumentModel,
    *,
    code_ratio_threshold: float = 0.5,
    table_ratio_threshold: float = 0.4,
) -> str:
    """Return a coarse document profile: ``"technical" | "prose" | "mixed"``.

    Signals: code/table char ratios across all blocks, plus the SAD-template
    heading fingerprint (:func:`doc_router.detect_doc_type`). A doc that is
    code/table-heavy or matches the SAD template is *technical*; one with almost
    no code/tables is *prose*; everything else (e.g. a tour doc mixing prose and
    code) is *mixed*.
    """
    from .doc_router import detect_doc_type

    blocks = [b for section in doc.iter_sections() for b in section.blocks]
    total = sum(len(b.text) for b in blocks)
    if total == 0:
        return "mixed"
    code_ratio = sum(len(b.text) for b in blocks if b.content_type == ContentType.CODE) / total
    table_ratio = sum(len(b.text) for b in blocks if b.content_type == ContentType.TABLE) / total

    if (
        detect_doc_type(doc) == "sad"
        or code_ratio >= code_ratio_threshold
        or table_ratio >= table_ratio_threshold
    ):
        return "technical"
    if code_ratio < _PROFILE_PROSE_CODE_MAX and table_ratio < _PROFILE_PROSE_TABLE_MAX:
        return "prose"
    return "mixed"


# ── Deterministic keyphrase extraction (RAKE) for prose sections ───────────────
# RAKE scores candidate phrases using ONLY the section's own text (a stopword list
# + word co-occurrence), so a chunk's keyphrases — and therefore its vector — are a
# pure function of its content: reproducible, no corpus state, no model. Used to
# put rich multi-word prose phrases into the embed `keywords:` line for non-technical
# sections, where the casing-based entity patterns find little. Pipeline-injected
# into chunking via the entity_fn seam, gated to prose-genre chunks.

# Compact English stopword set — phrase boundaries for RAKE. Kept small and generic
# (articles, prepositions, conjunctions, pronouns, auxiliaries) so domain nouns are
# never dropped.
_RAKE_STOPWORDS = frozenset(
    {
        "a",
        "an",
        "the",
        "and",
        "or",
        "but",
        "nor",
        "so",
        "yet",
        "for",
        "of",
        "to",
        "in",
        "on",
        "at",
        "by",
        "as",
        "is",
        "are",
        "was",
        "were",
        "be",
        "been",
        "being",
        "am",
        "it",
        "its",
        "this",
        "that",
        "these",
        "those",
        "with",
        "from",
        "into",
        "onto",
        "about",
        "over",
        "under",
        "between",
        "through",
        "during",
        "before",
        "after",
        "above",
        "below",
        "up",
        "down",
        "out",
        "off",
        "if",
        "then",
        "else",
        "than",
        "when",
        "while",
        "where",
        "which",
        "who",
        "whom",
        "whose",
        "what",
        "why",
        "how",
        "all",
        "any",
        "both",
        "each",
        "few",
        "more",
        "most",
        "other",
        "some",
        "such",
        "no",
        "not",
        "only",
        "own",
        "same",
        "too",
        "very",
        "can",
        "will",
        "just",
        "should",
        "now",
        "also",
        "we",
        "you",
        "they",
        "he",
        "she",
        "i",
        "our",
        "your",
        "their",
        "his",
        "her",
        "them",
        "us",
        "me",
        "my",
        "do",
        "does",
        "did",
        "done",
        "have",
        "has",
        "had",
        "having",
        "would",
        "could",
        "may",
        "might",
        "must",
        "shall",
        "there",
        "here",
        "because",
        "via",
        "per",
        "etc",
    }
)
# A word token or a run of other chars. Internal -, _, ., + are allowed only
# *between* alphanumerics (so identifiers like ``v1.2``/``well-known`` survive),
# but a trailing period/comma is NOT absorbed — it stays a boundary so phrases do
# not run across sentence ends ("quarterly. access").
_RAKE_TOKEN = re.compile(r"[A-Za-z0-9]+(?:[._+\-][A-Za-z0-9]+)*|[^A-Za-z0-9]+")


def extract_keyphrases(text: str, *, top_n: int = 6, max_phrase_words: int = 4) -> list[str]:
    """Return up to *top_n* RAKE keyphrases from *text* (deterministic, model-free).

    Candidate phrases are runs of content words bounded by stopwords / punctuation;
    each word scores ``degree/frequency`` (RAKE), and a phrase scores the sum of its
    words — favouring distinctive multi-word phrases. Output is lowercased and
    deterministically ranked (score desc, then phrase text), so identical input
    always yields identical keyphrases (and identical vectors).
    """
    phrases: list[list[str]] = []
    current: list[str] = []

    def flush() -> None:
        nonlocal current
        if current:
            phrases.append(current)
            current = []

    for tok in _RAKE_TOKEN.findall(text):
        if tok[0].isalnum():
            w = tok.lower()
            if w in _RAKE_STOPWORDS or w.isdigit() or len(w) < 3:
                flush()
            else:
                current.append(w)
                if len(current) >= max_phrase_words:
                    flush()
        elif tok.strip():  # a punctuation run (not pure whitespace) ends a phrase
            flush()
    flush()

    if not phrases:
        return []

    freq: dict[str, int] = {}
    degree: dict[str, int] = {}
    for ph in phrases:
        for w in ph:
            freq[w] = freq.get(w, 0) + 1
            degree[w] = degree.get(w, 0) + len(ph)  # RAKE: degree sums phrase lengths
    score = {w: degree[w] / freq[w] for w in freq}

    ranked: dict[str, float] = {}
    for ph in phrases:
        phrase_text = " ".join(ph)
        s = sum(score[w] for w in ph)
        if s > ranked.get(phrase_text, -1.0):
            ranked[phrase_text] = s

    ordered = sorted(ranked.items(), key=lambda kv: (-kv[1], kv[0]))
    return [p for p, _ in ordered[:top_n]]


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
    for match in _ENDPOINT_PATTERN.finditer(text):
        found.add(f"{match.group(1)} {match.group(2)}")
    if extra_terms:
        # Map each lower-cased hit back to the supplied spelling so output is
        # stable regardless of how the term is cased in the text.
        canonical = {t.strip().lower(): t.strip() for t in extra_terms if t and t.strip()}
        pattern = _compile_terms(canonical)
        if pattern is not None:
            for match in pattern.finditer(text):
                found.add(canonical.get(match.group(1).lower(), match.group(1)))
    return sorted(found)


# Admonition label at the start of a blockquote line: ``> **Note**``, ``> [!TIP]``,
# ``> WARNING:`` — optional bold/underscore emphasis or ``[!...]`` callout syntax.
_ADMONITION_RE = re.compile(
    r"(?im)^\s*>\s*(?:\[!\s*)?(?:\*\*|__)?\s*"
    r"(note|warning|tip|important|caution|info|danger|attention)\b"
)


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

    # Admonition / callout flavour, recovered from a blockquote whose first token is
    # a known label (``> **Note**``, ``> [!WARNING]``, ``> CAUTION:`` …). Emitted as
    # an ``admonition:<kind>`` tag so a warning/caution passage is filterable and the
    # signal reaches the embed header — no new ContentType or model change needed.
    for kind in {m.lower() for m in _ADMONITION_RE.findall(blocks_text)}:
        tag = f"admonition:{kind}"
        if tag not in tags:
            tags.append(tag)

    return tags


def enrich_section(
    section: Section,
    entity_terms: Iterable[str] | None = None,
    *,
    inventory: EntityInventory | None = None,
    directions: dict[str, Direction] | None = None,
    confidence_threshold: float = 0.6,
) -> None:
    """Mutate *section* in place.

    Always applies the legacy enrichment (section_type, entities, tags). When an
    *inventory* is supplied, the records for this section are *additionally* routed
    into depends_on/exposes/metadata by field name (see :func:`_apply_inventory`).
    The inventory path is additive — legacy enrichment is orthogonal and always
    runs — so existing callers that pass no inventory behave exactly as before.
    """
    section.section_type = classify_section_type(section.title)
    section.genre = classify_genre(section)

    all_text = section.title + "\n" + "\n".join(b.text for b in section.blocks)
    section.entities = extract_entities(all_text, entity_terms)
    section.tags = extract_tags(section.title, section.section_type, all_text)

    if inventory:
        records = inventory.get(section.section_id, [])
        if records:
            _apply_inventory(section, records, directions or {}, confidence_threshold)

    for sub in section.subsections:
        enrich_section(
            sub,
            entity_terms,
            inventory=inventory,
            directions=directions,
            confidence_threshold=confidence_threshold,
        )


def enrich_document(
    doc: DocumentModel,
    entity_terms: Iterable[str] | None = None,
    *,
    inventory: EntityInventory | None = None,
    directions: dict[str, Direction] | None = None,
    confidence_threshold: float = 0.6,
) -> DocumentModel:
    """
    Apply semantic enrichment to all sections of *doc* and return it.

    *entity_terms* is an optional project vocabulary folded into entity
    extraction (see :func:`extract_entities`). When *inventory* is supplied (and
    *directions* is not), the reviewed ``config/field_directions.yaml`` is loaded
    once to route directional fields. The mutation is in-place for performance;
    the same object is returned to allow chaining.
    """
    if inventory is not None and directions is None:
        directions = load_field_directions()
    for section in doc.root_sections:
        enrich_section(
            section,
            entity_terms,
            inventory=inventory,
            directions=directions,
            confidence_threshold=confidence_threshold,
        )
    return doc


def _append_unique(target: list[str], value: str) -> None:
    if value not in target:
        target.append(value)


def _write_to_field(
    section: Section, record: EntityRecord, directions: dict[str, Direction]
) -> None:
    """Route one above-threshold record to exactly one field.

    direction (by field name) → depends_on/exposes; a named non-directional field
    → ``metadata.<field>``; an unnamed (prose) field → ``metadata.raw_entities``.
    Direction is decided only by name, never guessed.
    """
    direction = resolve_direction(record.field, directions)
    if direction == "depends_on":
        _append_unique(section.depends_on, record.canonical)
    elif direction == "exposes":
        _append_unique(section.exposes, record.canonical)
    elif record.field:
        _append_unique(section.metadata.setdefault(record.field, []), record.canonical)
    else:
        _append_unique(section.metadata.setdefault("raw_entities", []), record.canonical)


def _apply_inventory(
    section: Section,
    records: list[EntityRecord],
    directions: dict[str, Direction],
    confidence_threshold: float,
) -> None:
    """Reconcile a section's records and write each to exactly one field.

    Below-threshold records go to the audit-only ``metadata.raw_entities`` bucket;
    above-threshold records route via :func:`_write_to_field`. Conservation: every
    reconciled canonical lands in exactly one place, nothing is dropped.
    """
    for record in reconcile(records):
        if record.confidence < confidence_threshold:
            _append_unique(section.metadata.setdefault("raw_entities", []), record.canonical)
        else:
            _write_to_field(section, record, directions)


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
    Fenced code is blanked before mining (mirrors :func:`extract_prose._section_text`)
    so ALLCAPS tokens inside code (a ``brush: java`` DSL's ``FILE``/``REPLACE`` …)
    don't pollute the corpus vocabulary; inline ``code`` is left intact.
    """
    text = section.title + "\n" + "\n".join(b.text for b in section.blocks)
    found.update(_collect_raw_terms(_FENCED.sub(" ", text)))
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
