"""Tests for sdd_pipeline.detection — optional per-document language detection."""

from __future__ import annotations

import pytest

from sdd_pipeline.detection import detect_language, langdetect_available


class TestDetectLanguageFallbacks:
    """These never need langdetect — they exercise the graceful-degradation paths."""

    def test_empty_text_returns_default(self):
        assert detect_language("") == "en"
        assert detect_language("   ", default="de") == "de"

    def test_default_is_normalized(self):
        # An unsupported default still degrades to a supported code.
        assert detect_language("", default="xx") == "en"

    def test_available_returns_bool(self):
        assert isinstance(langdetect_available(), bool)

    def test_missing_dependency_returns_default(self, monkeypatch):
        # Simulate langdetect not being importable → fall back to default.
        import builtins

        real_import = builtins.__import__

        def fake_import(name, *args, **kwargs):
            if name == "langdetect" or name.startswith("langdetect."):
                raise ImportError("simulated missing langdetect")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", fake_import)
        assert detect_language("Das ist ein deutscher Satz.", default="en") == "en"


@pytest.mark.skipif(not langdetect_available(), reason="langdetect not installed")
class TestDetectLanguageReal:
    def test_detects_german(self):
        assert (
            detect_language(
                "Die Authentifizierung erfolgt über Tokens und die Architektur ist modular."
            )
            == "de"
        )

    def test_detects_french(self):
        assert (
            detect_language(
                "La sécurité des données personnelles est une priorité absolue du système."
            )
            == "fr"
        )

    def test_detects_italian(self):
        assert (
            detect_language("La sicurezza dei dati personali è una priorità assoluta del sistema.")
            == "it"
        )

    def test_detects_english(self):
        assert (
            detect_language(
                "Authentication uses tokens and the architecture is modular and scalable."
            )
            == "en"
        )

    def test_out_of_allowed_falls_back(self):
        # Spanish is not in SUPPORTED_LANGUAGES → fall back to default.
        spanish = "La seguridad de los datos personales es una prioridad absoluta del sistema."
        assert detect_language(spanish, default="en") == "en"

    def test_deterministic(self):
        text = "Die Bereitstellung erfolgt über Kubernetes und Helm in der Cloud."
        assert detect_language(text) == detect_language(text)
