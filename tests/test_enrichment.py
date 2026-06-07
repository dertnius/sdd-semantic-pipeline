"""Tests for sdd_pipeline.enrichment."""

from __future__ import annotations

import pytest

from sdd_pipeline.enrichment import (
    classify_section_type,
    enrich_document,
    enrich_section,
    extract_entities,
    extract_tags,
    scan_corpus,
)
from sdd_pipeline.models import (
    ContentBlock,
    ContentType,
    DocumentMetadata,
    DocumentModel,
    Section,
    SectionType,
)


def _doc(doc_id: str, title: str, body: str) -> DocumentModel:
    """Single-section DocumentModel for corpus-scan tests."""
    return DocumentModel(
        doc_id=doc_id,
        metadata=DocumentMetadata(title=title, space="SP"),
        root_sections=[
            Section(
                level=1,
                title=title,
                section_id="s1",
                breadcrumb=[title],
                blocks=[ContentBlock(block_id="b1", content_type=ContentType.PARAGRAPH, text=body)],
            )
        ],
    )


class TestClassifySectionType:
    @pytest.mark.parametrize(
        "title, expected",
        [
            ("Overview", SectionType.OVERVIEW),
            ("Introduction", SectionType.OVERVIEW),
            ("Summary", SectionType.OVERVIEW),
            ("Background", SectionType.OVERVIEW),
            ("Architecture", SectionType.ARCHITECTURE),
            ("System Design", SectionType.ARCHITECTURE),
            ("High-Level Design", SectionType.ARCHITECTURE),
            ("API Contract", SectionType.API),
            ("REST Endpoints", SectionType.API),
            ("OpenAPI Schema", SectionType.API),
            ("Design Decision", SectionType.DECISION),
            ("ADR-004: Use JWT", SectionType.DECISION),
            ("Rationale", SectionType.DECISION),
            ("Deployment", SectionType.DEPLOYMENT),
            ("Kubernetes Config", SectionType.DEPLOYMENT),
            ("Helm Values", SectionType.DEPLOYMENT),
            ("Data Model", SectionType.DATA_MODEL),
            ("Entity Schema", SectionType.DATA_MODEL),
            ("Database Tables", SectionType.DATA_MODEL),
            ("Security", SectionType.SECURITY),
            ("Authentication Flow", SectionType.SECURITY),
            ("Authorization Rules", SectionType.SECURITY),
            ("JWT Configuration", SectionType.SECURITY),
            ("Random Section", SectionType.CONTENT),
            ("Meeting Notes", SectionType.CONTENT),
            # ── ADR/AIP decision-record types ──────────────────────────────
            ("Considerations", SectionType.ALTERNATIVE),
            ("Options Considered", SectionType.ALTERNATIVE),
            ("Other considerations?", SectionType.ALTERNATIVE),
            ("Pro arguments", SectionType.TRADEOFF),
            ("Trade-off Analysis", SectionType.TRADEOFF),
            ("Are there any downsides to this change?", SectionType.CONSEQUENCE),
            ("Which users are affected by the change?", SectionType.CONSEQUENCE),
            ('What defines this AIP as "done"?', SectionType.DONE_CRITERIA),
            ("Acceptance Criteria", SectionType.DONE_CRITERIA),
            ("Motivation", SectionType.OVERVIEW),
            ("What problem does it solve?", SectionType.OVERVIEW),
            # "in context of" must NOT win OVERVIEW over the migration signal.
            (
                "What is the level of migration effort needed (in context of Airflow 3)?",
                SectionType.CONSEQUENCE,
            ),
        ],
    )
    def test_known_titles(self, title: str, expected: SectionType):
        result = classify_section_type(title)
        assert result == expected, f"{title!r} → {result.value!r}, want {expected.value!r}"

    def test_case_insensitive(self):
        assert classify_section_type("OVERVIEW") == SectionType.OVERVIEW
        assert classify_section_type("api CONTRACT") == SectionType.API

    def test_empty_string_returns_content(self):
        assert classify_section_type("") == SectionType.CONTENT

    @pytest.mark.parametrize(
        "title, expected",
        [
            # "structure" must not match inside "infra*structure*" (ARCHITECTURE);
            # DEPLOYMENT's own "infrastructure" keyword should win.
            ("Infrastructure", SectionType.DEPLOYMENT),
            # "api" must not match inside "r*api*d Prototyping".
            ("Rapid Prototyping", SectionType.CONTENT),
        ],
    )
    def test_no_substring_collisions(self, title: str, expected: SectionType):
        result = classify_section_type(title)
        assert result == expected, f"{title!r} → {result.value!r}, want {expected.value!r}"

    def test_suitable_does_not_match_table(self):
        # "table" must not match inside "sui*table*" → not DATA_MODEL.
        assert classify_section_type("Suitable Options") != SectionType.DATA_MODEL


class TestExtractEntities:
    def test_extracts_service_name(self):
        entities = extract_entities("The AuthService calls UserService.")
        # Should find at least one of them (depends on which suffix patterns match)
        assert "AuthService" in entities or "UserService" in entities

    def test_extracts_infrastructure(self):
        entities = extract_entities("Uses Redis caching and PostgreSQL for persistence.")
        assert "Redis" in entities
        assert "PostgreSQL" in entities

    def test_extracts_protocols(self):
        entities = extract_entities("Auth uses JWT and OAuth2 with mTLS.")
        assert "JWT" in entities
        assert "OAuth2" in entities or "OAuth" in entities

    def test_extracts_kubernetes(self):
        entities = extract_entities("Deployed on Kubernetes via Helm.")
        assert "Kubernetes" in entities or "Helm" in entities

    def test_no_false_positives_from_common_words(self):
        entities = extract_entities("This document describes the overall system.")
        assert "This" not in entities
        assert "describes" not in entities

    def test_empty_string(self):
        assert extract_entities("") == []

    def test_result_is_sorted(self):
        entities = extract_entities("Redis PostgreSQL Kafka")
        assert entities == sorted(entities)

    def test_extra_terms_are_surfaced(self):
        text = "The triggerer re-queues the KPO task without re-scheduling."
        entities = extract_entities(text, extra_terms=["KPO", "triggerer", "XCom"])
        assert "KPO" in entities
        assert "triggerer" in entities
        assert "XCom" not in entities  # not mentioned in the text

    def test_extra_terms_use_canonical_spelling(self):
        # Term matches case-insensitively but is returned in the supplied form.
        entities = extract_entities("we use kpo heavily", extra_terms=["KPO"])
        assert "KPO" in entities
        assert "kpo" not in entities

    def test_extra_terms_none_is_noop(self):
        assert extract_entities("plain text", extra_terms=None) == []


class TestExtractTags:
    def test_section_type_always_in_tags(self):
        tags = extract_tags("API", SectionType.API, "content")
        assert "api" in tags

    def test_code_language_in_tags(self):
        tags = extract_tags("Code", SectionType.CONTENT, "```python\ncode\n```")
        assert "lang:python" in tags

    def test_no_duplicate_tags(self):
        tags = extract_tags("API", SectionType.API, "```json\n{}\n```")
        assert len(tags) == len(set(tags))

    def test_indented_code_fence_detected(self):
        # Fence indented under a list item still yields a lang tag.
        tags = extract_tags("Setup", SectionType.CONTENT, "  ```python\n  x = 1\n  ```")
        assert "lang:python" in tags

    def test_blockquote_code_fence_detected(self):
        # Fence prefixed by a blockquote marker still yields a lang tag.
        tags = extract_tags("Note", SectionType.CONTENT, "> ```yaml\n> a: 1\n> ```")
        assert "lang:yaml" in tags


class TestEnrichSection:
    def test_section_type_set(self):
        section = Section(
            level=1,
            title="Overview",
            section_id="s1",
            breadcrumb=["Overview"],
        )
        enrich_section(section)
        assert section.section_type == SectionType.OVERVIEW

    def test_entities_populated(self):
        from sdd_pipeline.models import ContentBlock, ContentType

        section = Section(
            level=2,
            title="Architecture",
            section_id="s2",
            breadcrumb=["Root", "Architecture"],
            blocks=[
                ContentBlock(
                    block_id="b1",
                    content_type=ContentType.PARAGRAPH,
                    text="AuthService uses Redis and PostgreSQL.",
                )
            ],
        )
        enrich_section(section)
        assert "Redis" in section.entities
        assert "PostgreSQL" in section.entities

    def test_subsections_enriched_recursively(self):
        parent = Section(
            level=1,
            title="Root",
            section_id="root",
            breadcrumb=["Root"],
            subsections=[
                Section(
                    level=2,
                    title="Architecture",
                    section_id="arch",
                    breadcrumb=["Root", "Architecture"],
                )
            ],
        )
        enrich_section(parent)
        assert parent.subsections[0].section_type == SectionType.ARCHITECTURE


class TestEnrichDocument:
    def test_returns_same_object(self, sample_document_model: DocumentModel):
        result = enrich_document(sample_document_model)
        assert result is sample_document_model

    def test_all_sections_classified(self, sample_document_model: DocumentModel):
        doc = enrich_document(sample_document_model)
        for section in doc.iter_sections():
            assert isinstance(section.section_type, SectionType)

    def test_known_sections_classified_correctly(self, sample_document_model: DocumentModel):
        doc = enrich_document(sample_document_model)
        section_map = {s.title: s for s in doc.iter_sections()}

        assert section_map["Overview"].section_type == SectionType.OVERVIEW
        assert section_map["Architecture"].section_type == SectionType.ARCHITECTURE
        assert section_map["API Contract"].section_type == SectionType.API
        assert section_map["Design Decision"].section_type == SectionType.DECISION
        assert section_map["Deployment"].section_type == SectionType.DEPLOYMENT


class TestScanCorpus:
    def test_discovers_allcaps_and_backtick_terms(self):
        docs = [
            _doc("d1", "Design", "We apply the CQRS pattern across services."),
            _doc("d2", "Config", "Runs in the `kube-system` namespace."),
        ]
        vocab = scan_corpus(docs)
        assert "CQRS" in vocab
        assert "kube-system" in vocab

    def test_respects_allcaps_stoplist(self):
        # Generic allcaps noise is dropped; note HTTP/TLS are kept because they are
        # legitimate protocol entities matched by _PROTOCOL_PATTERN, not the
        # allcaps path the stoplist guards.
        vocab = scan_corpus([_doc("d1", "Notes", "TODO and FIXME over JSON via the API.")])
        assert "TODO" not in vocab
        assert "FIXME" not in vocab
        assert "JSON" not in vocab
        assert "API" not in vocab

    def test_drops_sql_keyword_noise(self):
        # SQL keywords appearing as uppercase tokens in code are not entities.
        body = "Run `UPDATE t SET x = 1 WHERE id = 2` AND then SELECT NOT NULL."
        vocab = scan_corpus([_doc("d1", "Query", body)])
        for kw in ("UPDATE", "SET", "WHERE", "AND", "SELECT", "NOT", "NULL"):
            assert kw not in vocab, f"{kw} should be stoplisted"

    def test_seed_terms_bypass_patterns_and_stoplist(self):
        # XCom (mixed-case) and triggerer (lowercase) match no pattern, but seeded
        # project terms are surfaced regardless.
        vocab = scan_corpus(
            [_doc("d1", "Doc", "plain prose with no matching tokens")],
            seed_terms=["XCom", "triggerer", "KPO"],
        )
        assert {"XCom", "triggerer", "KPO"} <= set(vocab)

    def test_respects_min_length(self):
        # "DDD" (3 chars) kept; a 2-char acronym would be dropped by default.
        vocab = scan_corpus([_doc("d1", "Approach", "We follow DDD here.")], min_length=4)
        assert "DDD" not in vocab

    def test_merges_seed_terms(self):
        vocab = scan_corpus([_doc("d1", "Doc", "plain prose")], seed_terms=["LegacyTerm"])
        assert "LegacyTerm" in vocab

    def test_result_is_sorted_and_deduped(self):
        docs = [_doc("d1", "A", "CQRS CQRS BFF"), _doc("d2", "B", "BFF")]
        vocab = scan_corpus(docs)
        assert vocab == sorted(set(vocab))

    def test_read_only_does_not_enrich_sections(self):
        doc = _doc("d1", "Doc", "We apply CQRS.")
        scan_corpus([doc])
        section = doc.root_sections[0]
        # scan_corpus must not mutate section attributes (enrichment's job).
        assert section.entities == []
        assert section.tags == []
