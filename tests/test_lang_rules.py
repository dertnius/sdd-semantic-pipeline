"""Tests for sdd_pipeline.lang_rules — the per-language rule-pack registry."""

from __future__ import annotations

import re

import pytest

from sdd_pipeline.lang_rules import (
    DEFAULT_LANGUAGE,
    SUPPORTED_LANGUAGES,
    get_lang_pack,
    normalize_language,
)
from sdd_pipeline.models import Genre, SectionType


def test_supported_languages():
    assert SUPPORTED_LANGUAGES == ("en", "de", "fr", "it")
    assert DEFAULT_LANGUAGE == "en"


class TestNormalizeLanguage:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("de", "de"),
            ("DE", "de"),
            ("de-DE", "de"),
            ("de_AT", "de"),
            ("fr-CA", "fr"),
            ("IT", "it"),
            ("en", "en"),
        ],
    )
    def test_known_codes(self, raw, expected):
        assert normalize_language(raw) == expected

    @pytest.mark.parametrize("raw", ["", None, "xx", "klingon", "  ", "zz-ZZ"])
    def test_unknown_falls_back_to_english(self, raw):
        assert normalize_language(raw) == "en"


def test_get_lang_pack_fallback_is_english():
    assert get_lang_pack("xx").code == "en"
    assert get_lang_pack(None).code == "en"
    assert get_lang_pack("de").code == "de"


class TestPackCompleteness:
    """Every supported language must cover the full enum surface, so a doc in any
    language is classifiable and a 5th language can't silently omit a rule."""

    @pytest.mark.parametrize("lang", SUPPORTED_LANGUAGES)
    def test_all_section_types_present(self, lang):
        pack = get_lang_pack(lang)
        covered = set(pack.section_rules)
        # Every SectionType except the null CONTENT must have keywords.
        expected = set(SectionType) - {SectionType.CONTENT}
        assert covered == expected, f"{lang} missing {expected - covered}"
        assert all(kws for kws in pack.section_rules.values())

    @pytest.mark.parametrize("lang", SUPPORTED_LANGUAGES)
    def test_all_named_genres_present(self, lang):
        pack = get_lang_pack(lang)
        covered = set(pack.genre_title_rules)
        # GENERAL/NARRATIVE are body-derived, never title keywords.
        expected = {Genre.GLOSSARY, Genre.FAQ, Genre.HOWTO, Genre.POLICY}
        assert covered == expected, f"{lang} missing {expected - covered}"

    @pytest.mark.parametrize("lang", SUPPORTED_LANGUAGES)
    def test_scalar_fields_populated(self, lang):
        pack = get_lang_pack(lang)
        assert pack.imperative_verbs, f"{lang} has no imperative verbs"
        assert pack.rake_stopwords, f"{lang} has no stopwords"
        assert pack.admonition_labels, f"{lang} has no admonition labels"
        assert pack.snowball_name, f"{lang} has no snowball name"
        # modal_pattern must be a compilable alternation body.
        re.compile(r"\b(?:" + pack.modal_pattern + r")\b")

    @pytest.mark.parametrize("lang", SUPPORTED_LANGUAGES)
    def test_admonitions_include_english_callouts(self, lang):
        # `> [!NOTE]` syntax is used verbatim across locales, so every pack folds in EN.
        labels = {lbl.lower() for lbl in get_lang_pack(lang).admonition_labels}
        assert {"note", "warning", "tip"} <= labels
