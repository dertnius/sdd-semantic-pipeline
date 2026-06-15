"""Tests for sdd_pipeline.enrichment."""

from __future__ import annotations

import pytest

from sdd_pipeline.enrichment import (
    classify_document,
    classify_genre,
    classify_section_type,
    enrich_document,
    enrich_section,
    extract_entities,
    extract_keyphrases,
    extract_tags,
    scan_corpus,
)
from sdd_pipeline.models import (
    ContentBlock,
    ContentType,
    DocumentMetadata,
    DocumentModel,
    Genre,
    Section,
    SectionType,
)


def _genre_section(title: str, blocks: list[tuple[ContentType, str]]) -> Section:
    return Section(
        level=2,
        title=title,
        section_id="s",
        breadcrumb=[title],
        blocks=[
            ContentBlock(block_id=f"b{i}", content_type=ct, text=t)
            for i, (ct, t) in enumerate(blocks)
        ],
    )


class TestClassifyGenre:
    def test_glossary_from_definition_blocks(self):
        s = _genre_section(
            "Terms",
            [
                (
                    ContentType.DEFINITION,
                    "API — Application Programming Interface\nDTO — Data Transfer Object",
                )
            ],
        )
        assert classify_genre(s) == Genre.GLOSSARY

    def test_faq_from_question_paragraphs(self):
        s = _genre_section(
            "Common questions",
            [
                (ContentType.PARAGRAPH, "How do I reset my password?"),
                (ContentType.PARAGRAPH, "Open settings and click reset."),
                (ContentType.PARAGRAPH, "Where are logs stored?"),
                (ContentType.PARAGRAPH, "Under the logs directory."),
            ],
        )
        assert classify_genre(s) == Genre.FAQ

    def test_howto_from_imperative_ordered_list(self):
        s = _genre_section(
            "Onboarding",
            [(ContentType.LIST, "1. Install the CLI\n2. Configure the token\n3. Run the sync")],
        )
        assert classify_genre(s) == Genre.HOWTO

    def test_policy_from_modal_density(self):
        s = _genre_section(
            "Access rules",
            [
                (
                    ContentType.PARAGRAPH,
                    "Users must rotate keys quarterly. Access shall be revoked on exit. Secrets must not be shared.",
                )
            ],
        )
        assert classify_genre(s) == Genre.POLICY

    def test_narrative_fallback_for_plain_prose(self):
        s = _genre_section(
            "Background",
            [
                (
                    ContentType.PARAGRAPH,
                    "This project began as an experiment to make search better over time.",
                )
            ],
        )
        assert classify_genre(s) == Genre.NARRATIVE

    def test_code_dominant_section_is_general(self):
        # Prose-ness gate: a small modal sentence cannot flip a code-dominant section.
        code = (ContentType.CODE, "```python\n" + "x = compute()\n" * 40 + "```")
        modal = (ContentType.PARAGRAPH, "You must run it.")
        assert classify_genre(_genre_section("Example", [code, modal])) == Genre.GENERAL

    def test_body_wins_over_conflicting_title(self):
        # Title says policy, but the body is clearly an FAQ → body wins.
        s = _genre_section(
            "Security Policy",
            [
                (ContentType.PARAGRAPH, "Is data encrypted at rest?"),
                (ContentType.PARAGRAPH, "Yes, with AES-256."),
                (ContentType.PARAGRAPH, "Who can access secrets?"),
                (ContentType.PARAGRAPH, "Only the platform team."),
            ],
        )
        assert classify_genre(s) == Genre.FAQ

    def test_title_promotes_when_body_silent(self):
        # Plain prose body (no detector fires) under a "Glossary" heading → title promotes.
        s = _genre_section(
            "Glossary",
            [(ContentType.PARAGRAPH, "This page collects shared vocabulary for the team.")],
        )
        assert classify_genre(s) == Genre.GLOSSARY

    def test_enrich_section_sets_genre(self):
        s = _genre_section(
            "FAQ",
            [
                (ContentType.PARAGRAPH, "What is this?"),
                (ContentType.PARAGRAPH, "A tool."),
                (ContentType.PARAGRAPH, "Why?"),
                (ContentType.PARAGRAPH, "Because."),
            ],
        )
        enrich_section(s)
        assert s.genre == Genre.FAQ


def _doc_with_blocks(blocks: list[tuple[ContentType, str]], title: str = "Doc") -> DocumentModel:
    section = Section(
        level=1,
        title=title,
        section_id="s",
        breadcrumb=[title],
        blocks=[
            ContentBlock(block_id=f"b{i}", content_type=ct, text=t)
            for i, (ct, t) in enumerate(blocks)
        ],
    )
    return DocumentModel(
        doc_id="d", metadata=DocumentMetadata(title=title), root_sections=[section]
    )


class TestClassifyDocument:
    def test_code_heavy_is_technical(self):
        doc = _doc_with_blocks(
            [
                (ContentType.CODE, "```python\n" + "x = 1\n" * 50 + "```"),
                (ContentType.PARAGRAPH, "Note."),
            ]
        )
        assert classify_document(doc) == "technical"

    def test_table_heavy_is_technical(self):
        doc = _doc_with_blocks(
            [(ContentType.TABLE, "| a | b |\n| --- | --- |\n" + "| 1 | 2 |\n" * 40)]
        )
        assert classify_document(doc) == "technical"

    def test_prose_only_is_prose(self):
        doc = _doc_with_blocks(
            [
                (
                    ContentType.PARAGRAPH,
                    "A narrative paragraph about the project history and its goals.",
                )
            ]
        )
        assert classify_document(doc) == "prose"

    def test_mixed_prose_and_some_code_is_mixed(self):
        doc = _doc_with_blocks(
            [
                (ContentType.PARAGRAPH, "P" * 200),
                (ContentType.CODE, "```python\n" + "y\n" * 30 + "```"),
            ]
        )
        assert classify_document(doc) == "mixed"

    def test_empty_doc_is_mixed(self):
        doc = DocumentModel(doc_id="e", metadata=DocumentMetadata(title="E"), root_sections=[])
        assert classify_document(doc) == "mixed"


class TestExtractKeyphrases:
    def test_extracts_multiword_phrase(self):
        text = (
            "The incident response procedure must be followed. "
            "Our incident response procedure is reviewed quarterly."
        )
        assert "incident response procedure" in extract_keyphrases(text)

    def test_deterministic(self):
        text = "Data retention policy applies here. The data retention policy is reviewed annually."
        assert extract_keyphrases(text) == extract_keyphrases(text)

    def test_drops_stopwords_and_short_tokens(self):
        assert extract_keyphrases("the a of in on at is to") == []

    def test_respects_top_n(self):
        text = ". ".join(f"alpha{i} beta{i} delta" for i in range(10))
        assert len(extract_keyphrases(text, top_n=3)) <= 3

    def test_phrases_do_not_span_sentence_boundaries(self):
        # A trailing period must end a phrase, not be absorbed into a word.
        kps = extract_keyphrases("Rotate credentials quarterly. Access is revoked on exit.")
        assert all("." not in k for k in kps)
        assert "quarterly access" not in kps


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

    def test_extracts_http_endpoints(self):
        entities = extract_entities("Call POST /v1/orders then GET /v1/orders/{id} to confirm.")
        assert "POST /v1/orders" in entities
        assert "GET /v1/orders/{id}" in entities

    def test_endpoint_pattern_ignores_plain_prose(self):
        # No uppercase method + leading slash → no endpoint false-positive.
        assert not any("/" in e for e in extract_entities("Get the orders and put them away."))

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
