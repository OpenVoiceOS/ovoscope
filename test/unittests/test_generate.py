"""``ovoscope generate``: golden rows drafted from a skill's own templates.

A skill's ``.intent`` lines are what Padatious was trained on, so a
sentence drawn from them must reach its own intent. These tests pin the
contract the consumers (ovos-tui-client, Klondike, a skill's own CI) rely
on: rows load through ``load_golden_rows`` and ``load_intent_cases``, are
marked as generated, skip exactly what ovos-workshop 9.x drops, stay under
the cap, and come out the same every time.
"""
import json
from pathlib import Path

import pytest

from ovoscope.cli import _build_parser, cmd_generate
from ovoscope.generate import (EXIT_EXISTS, EXIT_NOTHING_GENERATED,
                               REASON_ADJACENT_SLOTS, REASON_EMPTY_SAMPLE,
                               REASON_SLOT_ONLY, REASON_SLOT_ONLY_SAMPLE,
                               REASON_UNFILLED_SLOT, SOURCE_GENERATED,
                               WARNING_SINGLE_BRANCH, find_locale_dir,
                               generate_rows, write_golden_rows,
                               write_intent_cases)
from ovoscope.golden import load_golden_rows
from ovoscope.intent_cases import load_intent_cases

SKILL_ID = "ovos-skill-fixture.test"


def _skill(root: Path, files: dict, lang: str = "en-us",
           package: str = "") -> Path:
    """Write ``{relative path: text}`` under ``<root>[/<package>]/locale/<lang>``."""
    base = root / package / "locale" / lang if package else root / "locale" / lang
    for rel, text in files.items():
        path = base / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return root


def _utts(result, intent=None):
    return [r.utterance for r in result.rows
            if intent is None or r.intent_label == intent]


def _reasons(result):
    return sorted(s.reason for s in result.skipped)


# ---------------------------------------------------------------------------
# Expansion and slot filling
# ---------------------------------------------------------------------------
class TestExpansion:
    def test_alternatives_and_optionals_expand(self, tmp_path):
        _skill(tmp_path, {"greet.intent": "(hi|hello) [there]\n"})
        result = generate_rows(tmp_path, SKILL_ID, ["en-us"])
        assert sorted(_utts(result)) == ["hello", "hello there", "hi", "hi there"]

    def test_voc_references_are_inlined(self, tmp_path):
        _skill(tmp_path, {"play.intent": "play <thing>\n",
                          "thing.voc": "music\nthe radio\n"})
        result = generate_rows(tmp_path, SKILL_ID, ["en-us"])
        assert sorted(_utts(result)) == ["play music", "play the radio"]

    def test_slot_filled_from_entity_file(self, tmp_path):
        _skill(tmp_path, {"convert.intent": "convert 5 to {unit}\n",
                          "unit.entity": "inches\nmeters\n"})
        result = generate_rows(tmp_path, SKILL_ID, ["en-us"])
        assert sorted(_utts(result)) == ["convert 5 to inches",
                                         "convert 5 to meters"]
        assert result.rows[0].slot_sources == {"unit": "entity"}

    def test_slot_filled_from_default_by_name(self, tmp_path):
        _skill(tmp_path, {"count.intent": "count to {number}\n"})
        result = generate_rows(tmp_path, SKILL_ID, ["en-us"])
        assert _utts(result) == ["count to 10"]
        assert result.rows[0].slot_sources == {"number": "default"}

    def test_slot_filled_from_default_by_declared_type(self, tmp_path):
        # the name says nothing; the OVOS-INTENT-1 type prefix does
        _skill(tmp_path, {"weather.intent": "weather in {location:spot}\n"})
        result = generate_rows(tmp_path, SKILL_ID, ["en-us"])
        assert _utts(result) == ["weather in london"]

    def test_slot_value_argument_beats_default_but_not_entity(self, tmp_path):
        _skill(tmp_path, {"a.intent": "search for {query}\n",
                          "b.intent": "convert to {unit}\n",
                          "unit.entity": "inches\n"})
        result = generate_rows(tmp_path, SKILL_ID, ["en-us"],
                               slot_values={"query": ["the moon"],
                                            "unit": ["ignored"]})
        assert _utts(result, "a") == ["search for the moon"]
        assert _utts(result, "b") == ["convert to inches"]
        assert result.rows[0].slot_sources == {"query": "argument"}

    def test_every_language_when_none_is_given(self, tmp_path):
        _skill(tmp_path, {"greet.intent": "hello\n"}, lang="en-US")
        _skill(tmp_path, {"greet.intent": "hej\n"}, lang="da-dk")
        result = generate_rows(tmp_path, SKILL_ID)
        assert sorted((r.lang, r.utterance) for r in result.rows) == [
            ("da-DK", "hej"), ("en-US", "hello")]

    def test_lang_folder_case_and_subfolders(self, tmp_path):
        # weather keeps its intents under locale/en-US/intents/
        _skill(tmp_path, {"intents/greet.intent": "hello\n"},
               lang="en-US", package="my_skill")
        result = generate_rows(tmp_path, SKILL_ID, ["en-us"])
        assert _utts(result) == ["hello"]
        assert result.rows[0].lang == "en-US"
        assert result.rows[0].source_file == \
            "my_skill/locale/en-US/intents/greet.intent"

    def test_locale_under_tests_is_ignored(self, tmp_path):
        _skill(tmp_path, {"greet.intent": "hello\n"}, package="test")
        assert find_locale_dir(tmp_path) is None
        assert generate_rows(tmp_path, SKILL_ID).rows == []


# ---------------------------------------------------------------------------
# What is skipped, mirroring ovos-workshop 9.x
# ---------------------------------------------------------------------------
class TestSkipped:
    @pytest.mark.parametrize("template,reason", [
        ("play {artist} {album} now", REASON_ADJACENT_SLOTS),
        ("play {artist}{album} now", REASON_ADJACENT_SLOTS),
        ("turn on ()", REASON_EMPTY_SAMPLE),
        ("(on|)", REASON_EMPTY_SAMPLE),
        ("{query}", REASON_SLOT_ONLY),
    ])
    def test_template_ovos_workshop_drops_is_skipped(self, tmp_path, template,
                                                     reason):
        _skill(tmp_path, {"it.intent": f"{template}\nkeep me\n",
                          "artist.entity": "abba\n", "album.entity": "gold\n"})
        result = generate_rows(tmp_path, SKILL_ID, ["en-us"])
        assert _utts(result) == ["keep me"]
        assert _reasons(result) == [reason]
        skipped = result.skipped[0]
        assert (skipped.template, skipped.intent) == (template, "it")
        assert skipped.source_file == "locale/en-us/it.intent"

    def test_single_branch_group_is_generated_and_warned(self, tmp_path):
        # ovos-spec-tools folds (music) to music and ovos-workshop keeps it
        _skill(tmp_path, {"play.intent": "play (music)\n"})
        result = generate_rows(tmp_path, SKILL_ID, ["en-us"])
        assert _utts(result) == ["play music"]
        assert result.skipped == []
        assert [w.reason for w in result.warnings] == [WARNING_SINGLE_BRANCH]

    def test_slot_only_sample_is_skipped_rest_kept(self, tmp_path):
        _skill(tmp_path, {"say.intent": "{word} [please]\n"})
        result = generate_rows(tmp_path, SKILL_ID, ["en-us"],
                               slot_values={"word": ["hello"]})
        assert _utts(result) == ["hello please"]
        assert _reasons(result) == [REASON_SLOT_ONLY_SAMPLE]

    def test_unfilled_slot_is_skipped_not_guessed(self, tmp_path):
        _skill(tmp_path, {"search.intent": "search for {query}\nsearch\n"})
        result = generate_rows(tmp_path, SKILL_ID, ["en-us"])
        assert _utts(result) == ["search"]
        assert _reasons(result) == [REASON_UNFILLED_SLOT]
        assert "{query}" in result.skipped[0].detail

    def test_optional_unfilled_slot_keeps_the_samples_without_it(self, tmp_path):
        _skill(tmp_path, {"list.intent": "(create|add) items [{items}]\n"})
        result = generate_rows(tmp_path, SKILL_ID, ["en-us"])
        assert sorted(_utts(result)) == ["add items", "create items"]
        assert _reasons(result) == [REASON_UNFILLED_SLOT]

    def test_adapt_only_skill_gives_no_rows(self, tmp_path):
        _skill(tmp_path, {"weather.voc": "weather\n"})
        result = generate_rows(tmp_path, SKILL_ID, ["en-us"])
        assert result.rows == [] and result.intents == {}


# ---------------------------------------------------------------------------
# The cap and determinism
# ---------------------------------------------------------------------------
class TestCap:
    def _big(self, tmp_path):
        units = "".join(f"unit{i:03d}\n" for i in range(200))
        return _skill(tmp_path, {
            "convert.intent": "convert 5 to {unit}\nwhat is 5 in {unit}\n"
                              "(change|turn) 5 into {unit}\n",
            "unit.entity": units})

    def test_cap_holds_and_is_reported(self, tmp_path):
        result = generate_rows(self._big(tmp_path), SKILL_ID, ["en-us"],
                               max_per_intent=5)
        assert len(result.rows) == 5
        assert result.intents["en-US"]["convert"] == {
            "templates": 3, "rows": 5, "capped": True}

    def test_every_template_line_before_any_second(self, tmp_path):
        result = generate_rows(self._big(tmp_path), SKILL_ID, ["en-us"],
                               max_per_intent=3)
        assert [r.template for r in result.rows] == [
            "convert 5 to {unit}", "what is 5 in {unit}",
            "(change|turn) 5 into {unit}"]

    def test_entity_values_are_spread_not_first_n(self, tmp_path):
        result = generate_rows(self._big(tmp_path), SKILL_ID, ["en-us"],
                               max_per_intent=10)
        units = {r.utterance.split()[-1] for r in result.rows}
        assert len(units) > 3
        assert units != {f"unit{i:03d}" for i in range(len(units))}

    def test_same_checkout_same_rows(self, tmp_path):
        first = generate_rows(self._big(tmp_path), SKILL_ID, max_per_intent=7)
        second = generate_rows(tmp_path, SKILL_ID, max_per_intent=7)
        assert [r.as_dict() for r in first.rows] == \
            [r.as_dict() for r in second.rows]

    def test_not_capped_when_everything_fits(self, tmp_path):
        _skill(tmp_path, {"greet.intent": "(hi|hello)\n"})
        result = generate_rows(tmp_path, SKILL_ID, ["en-us"], max_per_intent=5)
        assert result.intents["en-US"]["greet"]["capped"] is False

    def test_cap_below_one_is_refused(self, tmp_path):
        with pytest.raises(ValueError):
            generate_rows(tmp_path, SKILL_ID, max_per_intent=0)


# ---------------------------------------------------------------------------
# Output formats
# ---------------------------------------------------------------------------
class TestOutput:
    def test_rows_load_as_golden_and_are_marked_generated(self, tmp_path):
        _skill(tmp_path, {"count.intent": "count to {number}\n"})
        result = generate_rows(tmp_path, SKILL_ID, ["en-us"])
        out = tmp_path / "rows.jsonl"
        with out.open("w", encoding="utf-8") as fh:
            write_golden_rows(result.rows, fh)
        (row,) = load_golden_rows(out)
        assert (row.utterance, row.lang, row.skill_id, row.expected_intent) == \
            ("count to 10", "en-US", SKILL_ID, "count")
        assert row.provenance["source"] == SOURCE_GENERATED
        assert row.provenance["machine_generated"] is True
        assert row.provenance["needs_manual"] is False
        assert row.provenance["template"] == "count to {number}"
        assert row.provenance["slot_sources"] == {"number": "default"}

    def test_intent_cases_load_and_carry_the_marker(self, tmp_path):
        _skill(tmp_path, {"greet.intent": "(hi|hello)\n",
                          "bye.intent": "bye\n"})
        result = generate_rows(tmp_path, SKILL_ID, ["en-us"])
        cases_dir = tmp_path / "cases"
        write_intent_cases(result.rows, cases_dir)
        cases = load_intent_cases(cases_dir, known_intents=["greet", "bye"])
        assert sorted((c.lang, c.intent, c.utterance) for c in cases) == [
            ("en-US", "bye", "bye"), ("en-US", "greet", "hello"),
            ("en-US", "greet", "hi")]
        text = (cases_dir / "en-US" / "greet.intent.test").read_text()
        assert text.startswith(f"# source: {SOURCE_GENERATED}")

    def test_intent_cases_never_overwrite_without_force(self, tmp_path):
        _skill(tmp_path, {"greet.intent": "hello\n"})
        result = generate_rows(tmp_path, SKILL_ID, ["en-us"])
        target = tmp_path / "cases" / "en-US" / "greet.intent.test"
        target.parent.mkdir(parents=True)
        target.write_text("hand written\n")
        with pytest.raises(FileExistsError):
            write_intent_cases(result.rows, tmp_path / "cases")
        assert target.read_text() == "hand written\n"
        write_intent_cases(result.rows, tmp_path / "cases", force=True)
        assert "hello" in target.read_text()

    def test_report_lists_skips_and_warnings(self, tmp_path):
        _skill(tmp_path, {"it.intent": "{a} {b} go\nplay (music)\n"})
        report = generate_rows(tmp_path, SKILL_ID, ["en-us"]).report()
        assert report["source"] == SOURCE_GENERATED
        assert report["rows"] == 1
        assert [s["reason"] for s in report["skipped"]] == [REASON_ADJACENT_SLOTS]
        assert [w["reason"] for w in report["warnings"]] == [WARNING_SINGLE_BRANCH]
        json.dumps(report)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
class TestCli:
    def _run(self, *argv):
        args = _build_parser().parse_args(["generate", *argv])
        return cmd_generate(args)

    def test_parser_defaults(self):
        args = _build_parser().parse_args(["generate", "--skill", SKILL_ID])
        assert (args.checkout, args.format, args.max_per_intent, args.lang) == \
            (".", "golden", 10, None)

    def test_writes_rows_to_stdout(self, tmp_path, capsys):
        _skill(tmp_path, {"greet.intent": "hello\n"})
        assert self._run("--skill", SKILL_ID, "--checkout", str(tmp_path),
                         "--lang", "en-us") == 0
        rows = [json.loads(l) for l in capsys.readouterr().out.splitlines()]
        assert [r["utterance"] for r in rows] == ["hello"]

    def test_out_report_and_slot(self, tmp_path):
        _skill(tmp_path, {"search.intent": "search for {query}\n"})
        out, report = tmp_path / "rows.jsonl", tmp_path / "report.json"
        assert self._run("--skill", SKILL_ID, "--checkout", str(tmp_path),
                         "--out", str(out), "--report", str(report),
                         "--slot", "query=the moon") == 0
        assert load_golden_rows(out)[0].utterance == "search for the moon"
        assert json.loads(report.read_text())["rows"] == 1

    def test_existing_out_needs_force(self, tmp_path):
        _skill(tmp_path, {"greet.intent": "hello\n"})
        out = tmp_path / "rows.jsonl"
        out.write_text("keep\n")
        with pytest.raises(SystemExit) as exc:
            self._run("--skill", SKILL_ID, "--checkout", str(tmp_path),
                      "--out", str(out))
        assert exc.value.code == EXIT_EXISTS
        assert out.read_text() == "keep\n"
        assert self._run("--skill", SKILL_ID, "--checkout", str(tmp_path),
                         "--out", str(out), "--force") == 0

    def test_no_templates_exits_2(self, tmp_path):
        _skill(tmp_path, {"weather.voc": "weather\n"})
        assert self._run("--skill", SKILL_ID, "--checkout",
                         str(tmp_path)) == EXIT_NOTHING_GENERATED

    def test_intent_cases_needs_out(self, tmp_path):
        with pytest.raises(SystemExit):
            self._run("--skill", SKILL_ID, "--checkout", str(tmp_path),
                      "--format", "intent-cases")

    def test_bad_slot_argument(self, tmp_path):
        with pytest.raises(SystemExit):
            self._run("--skill", SKILL_ID, "--checkout", str(tmp_path),
                      "--slot", "query")
