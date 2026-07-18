"""Tests for shared corpus pipeline utilities."""

from profiler.pipeline.utils import (
    make_slug,
    normalize_column_heuristics,
    normalize_tab_heuristics,
    token_match,
    write_json,
)


class TestWriteJson:
    def test_creates_parent_dirs(self, tmp_path):
        target = tmp_path / "sub" / "file.json"
        write_json(target, {"key": "value"})
        assert target.exists()
        assert target.read_text() == '{\n  "key": "value"\n}'

    def test_overwrites_existing(self, tmp_path):
        target = tmp_path / "file.json"
        target.write_text("old")
        write_json(target, {"new": True})
        assert '"new": true' in target.read_text()


class TestMakeSlug:
    def test_simple_text(self):
        assert make_slug("Hello World") == "hello_world"

    def test_special_chars(self):
        assert make_slug("Tab: 2023/Season!") == "tab_2023_season"

    def test_truncation(self):
        result = make_slug("a" * 100)
        assert len(result) == 50

    def test_empty_fallback(self):
        assert make_slug("") == "tab"
        assert make_slug("   ") == "tab"


class TestTokenMatch:
    def test_substring_mode(self):
        assert token_match("plan", "planting plan 2023", "substring") is True
        assert token_match("plan", "season overview", "substring") is False

    def test_word_mode(self):
        assert token_match("plan", "replant", "word") is False
        assert token_match("plan", "planting plan", "word") is True

    def test_default_mode(self):
        assert token_match("plan", "planting plan", "substring") is True


class TestNormalizeTabHeuristics:
    def test_empty_config_returns_defaults(self):
        result = normalize_tab_heuristics(None)
        assert result["operational_weight"] == 3
        assert result["reference_weight"] == 3
        assert result["derived_weight"] == -4
        assert result["match_mode"] == "substring"

    def test_custom_weights(self):
        result = normalize_tab_heuristics({"operational_weight": 5})
        assert result["operational_weight"] == 5

    def test_invalid_match_mode_falls_back(self):
        result = normalize_tab_heuristics({"match_mode": "invalid"})
        assert result["match_mode"] == "substring"

    def test_exclude_patterns_compiled(self):
        result = normalize_tab_heuristics({
            "tab_exclude_patterns": [
                {"pattern": "^_", "exclude": True, "penalty": -10}
            ]
        })
        assert len(result["tab_exclude_regexes"]) == 1

    def test_exclude_patterns_penalty_applied(self):
        result = normalize_tab_heuristics({
            "tab_exclude_patterns": [
                {"pattern": "temp", "penalty": -5}
            ]
        })
        assert len(result["exclude_patterns"]) == 1
        assert result["exclude_patterns"][0]["penalty"] == -5


class TestNormalizeColumnHeuristics:
    def test_empty_config_returns_empty_tokens(self):
        result = normalize_column_heuristics(None)
        assert result["domain_keyword_tokens"] == []

    def test_tokens_lowercased(self):
        result = normalize_column_heuristics({
            "domain_keyword_tokens": ["Crop", "FIELD"]
        })
        assert result["domain_keyword_tokens"] == ["crop", "field"]
