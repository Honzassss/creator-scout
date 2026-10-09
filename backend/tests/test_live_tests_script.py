"""scripts/live_tests.py without Apify: dry-run without a token, the budget guard, charge caps on every run,
no second paid run after an error, no re-run of saved tests without --rerun, redaction before saving, and a
report without personal text. A fake runner returns the HAND-MADE samples from tests/apify_samples/ (fictional
sample_* accounts). Nothing here calls Apify. Output goes to <DATA_DIR>/live-tests, and conftest points
DATA_DIR at a temp dir for every test."""

from __future__ import annotations

import importlib.util
import json
import re
import sys
from pathlib import Path

import pytest

from app import config
from app.sources.apify_provider import (
    ACT_BRAND,
    ACT_IG_COMMENT,
    ACT_IG_HASHTAG,
    ACT_IG_POST,
    ACT_IG_PROFILE,
    ACT_IG_SCRAPER,
    ACT_IG_SEARCH,
    ACT_NEWS,
    ACT_TT,
    ACT_TT_PROFILE,
    RunResult,
)

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts" / "live_tests.py"
HANDOFF = REPO / "docs" / "apify-pro-krystofa.md"
SAMPLES = Path(__file__).parent / "apify_samples"


def _load_script():
    spec = importlib.util.spec_from_file_location("creator_scout_live_tests", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


lt = _load_script()

YT_ITEMS = [
    {"id": "JsBZOcqZerk", "url": "https://www.youtube.com/watch?v=JsBZOcqZerk", "title": "Sample paid promo video",
     "text": "Sample description mentioning a sponsor", "channelName": "Sample Channel Person",
     "isPaidContent": True, "channelLocation": "CZ"},
    {"id": "1H20xp8Brnc", "url": "https://www.youtube.com/watch?v=1H20xp8Brnc", "title": "Sample ordinary video",
     "text": "Sample plain description", "channelName": "Sample Channel Person", "isPaidContent": False},
]


def sample(name: str) -> list[dict]:
    return json.loads((SAMPLES / name).read_text("utf-8"))["items"]


def items_for(actor: str, run_input: dict) -> list[dict]:
    if actor == ACT_IG_SEARCH:
        return sample("ig_search_places.json" if run_input.get("searchType") == "place" else "ig_search_users.json")
    files = {ACT_IG_HASHTAG: "ig_hashtag_posts.json", ACT_IG_SCRAPER: "ig_location_details.json",
             ACT_IG_PROFILE: "ig_profiles.json", ACT_IG_POST: "ig_posts_detailed.json",
             ACT_IG_COMMENT: "ig_comments.json", ACT_TT: "tt_search_user.json",
             ACT_TT_PROFILE: "tt_profile_videos.json", ACT_BRAND: "brand_collabs.json", ACT_NEWS: "news.json"}
    if actor in files:
        return sample(files[actor])
    if actor == lt.ACT_YT:
        return [dict(x) for x in YT_ITEMS]
    raise AssertionError(f"unexpected actor {actor}")


class FakeRunner:
    """Stands in for the Apify client (provider Runner signature)."""

    def __init__(self, usd: float | str = 0.01) -> None:
        self.calls: list[dict] = []
        self.usd = usd          # "cap": the run uses its whole max_total_charge_usd

    async def __call__(self, actor, run_input, *, max_items, max_usd, timeout_s):
        self.calls.append({"actor": actor, "input": run_input, "max_items": max_items, "max_usd": max_usd,
                           "timeout_s": timeout_s})
        used = max_usd if self.usd == "cap" else self.usd
        return RunResult(items=items_for(actor, run_input), status="SUCCEEDED", usd=used,
                         events={"result": 3}, run_id=f"fake{len(self.calls)}")


class ScriptedRunner:
    """Returns (or raises) the given outcomes one call at a time."""

    def __init__(self, *outcomes) -> None:
        self.outcomes = list(outcomes)
        self.calls: list[dict] = []

    async def __call__(self, actor, run_input, *, max_items, max_usd, timeout_s):
        self.calls.append({"actor": actor, "input": run_input, "max_usd": max_usd})
        out = self.outcomes.pop(0)
        if isinstance(out, BaseException):
            raise out
        return out


class NeverRunner:
    async def __call__(self, *a, **k):  # pragma: no cover - must not be reached
        raise AssertionError("a dry run must not start any actor")


@pytest.fixture
def fake_token(monkeypatch):
    monkeypatch.setenv("APIFY_TOKEN", "fake-token-for-tests")
    config.reload_settings()
    yield


def default_out() -> Path:
    return config.get_settings().data_dir / "live-tests"


@pytest.fixture
def full_run(fake_token, capsys):
    out = default_out()
    runner = FakeRunner()
    rc = lt.main(["--yes", "--force-t7"], runner=runner)
    printed = capsys.readouterr().out
    return {"rc": rc, "out": out, "runner": runner, "stdout": printed,
            "report": (out / "report.md").read_text("utf-8") if (out / "report.md").exists() else ""}


# ---------------------------------------------------------------------------------------------
# Dry-run and token
# ---------------------------------------------------------------------------------------------


def test_dry_run_works_without_token(capsys):
    assert config.get_settings().apify_token is None
    out = default_out()
    rc = lt.main(["--dry-run"], runner=NeverRunner())
    printed = capsys.readouterr().out
    assert rc == 0
    for k in lt.TEST_KEYS:
        assert re.search(rf"^{k}\s", printed, re.M), k
    assert "DRY-RUN" in printed and "token: chybí" in printed
    assert "Celkem 12 testů" in printed
    assert "max_total_charge_usd" in printed
    assert not out.exists()          # nothing saved


def test_live_without_token_exits_with_clear_message(capsys):
    rc = lt.main(["--yes", "--only", "T11"], runner=NeverRunner())
    err = capsys.readouterr().err
    assert rc == 2
    assert "APIFY_TOKEN" in err and "--dry-run" in err


def test_bad_only_value_is_rejected(capsys):
    assert lt.main(["--dry-run", "--only", "T13"]) == 2
    assert "T13" in capsys.readouterr().err


def test_report_only_without_token_and_without_data(capsys):
    out = default_out() / "empty"
    assert lt.main(["--report-only", "--out", str(out)]) == 0
    report = (out / "report.md").read_text("utf-8")
    assert "## Souhrn" in report and "nespuštěno" in report


# Keys the script may add to a handoff input: paid add-ons and extras without a safe schema default, always
# switched off explicitly (handoff, "Limity vždy výslovně"). Nothing else may differ from the handoff.
TT_OFF_KEYS = ("commentsPerPost", "topLevelCommentsPerPost", "maxRepliesPerComment", "maxFollowersPerProfile",
               "maxFollowingPerProfile")
OFF_EXTRAS = {"enhanceUserSearchWithFacebookPage": False, "keywordSearch": False, "extractDescriptions": False,
              "maxResultsShorts": 0, "maxResultStreams": 0, **{k: 0 for k in TT_OFF_KEYS}}
REQUIRED_OFF = {"T1a": ("enhanceUserSearchWithFacebookPage",), "T1b": ("enhanceUserSearchWithFacebookPage",),
                "T2a": ("enhanceUserSearchWithFacebookPage",), "T2b": ("enhanceUserSearchWithFacebookPage",),
                "T3": ("keywordSearch",), "T9a": TT_OFF_KEYS, "T9b": TT_OFF_KEYS, "T10": TT_OFF_KEYS,
                "T11": ("extractDescriptions",)}


def _matches_handoff(got: dict, expected: dict) -> None:
    assert {k: got.get(k, "<chybí>") for k in expected} == expected
    extra = {k: v for k, v in got.items() if k not in expected}
    bad = {k: v for k, v in extra.items()
           if k not in OFF_EXTRAS or v != OFF_EXTRAS[k] or type(v) is not type(OFF_EXTRAS[k])}
    assert not bad, bad


def test_fixed_inputs_match_the_handoff():
    """The first JSON block of each fixed test section in the handoff is contained in what the script sends;
    extra keys are only explicit off values from OFF_EXTRAS."""
    text = HANDOFF.read_text("utf-8")
    blocks: dict[str, list[dict]] = {}
    for m in re.finditer(r"^### (T\d+)\. .*?(?=^### |^## )", text, re.M | re.S):
        blocks[m.group(1)] = [json.loads(b) for b in re.findall(r"```json\n(.*?)\n```", m.group(0), re.S)]
    ns = lt.parse_args([])
    ctx = lt.Ctx(ns, Path("/nonexistent"))
    want = {"T1": ["T1a"], "T2": ["T2a"], "T3": ["T3"], "T8": ["T8a", "T8b"], "T9": ["T9a"], "T10": ["T10"],
            "T11": ["T11"], "T12": ["T12"]}
    every: dict[str, dict] = {}
    for key, labels in want.items():
        built = lt.TESTS[key].build(ctx, False)
        runs = {r.label: r.input for r in built.runs}
        every.update(runs)
        for label, expected in zip(labels, blocks[key]):
            _matches_handoff(runs[label], expected)
    _matches_handoff(every["T1b"], {**blocks["T1"][0], "liveSearch": True})
    _matches_handoff(every["T2b"], {**blocks["T2"][0], "liveSearch": True})
    # T9b: "totéž bez proxyCountryCode", sent as the schema default "None" rather than left out
    _matches_handoff(every["T9b"], {**blocks["T9"][0], "proxyCountryCode": "None"})
    assert every["T9b"]["proxyCountryCode"] == "None"
    for label, keys in REQUIRED_OFF.items():
        for k in keys:
            assert k in every[label] and every[label][k] == OFF_EXTRAS[k], (label, k)


# ---------------------------------------------------------------------------------------------
# Cost safety
# ---------------------------------------------------------------------------------------------


def test_budget_guard_stops_before_exceeding(fake_token, capsys):
    out = default_out()
    runner = FakeRunner(usd=0.02)
    budget = 0.30
    # T1 (worst 0.216) fits, T3 (0.26) no longer fits, T11 (0.04) still does.
    rc = lt.main(["--yes", "--only", "T1,T3,T11", "--budget", str(budget)], runner=runner)
    printed = capsys.readouterr().out
    assert rc == 0
    assert [c["actor"] for c in runner.calls] == [ACT_IG_SEARCH, ACT_IG_SEARCH, ACT_NEWS]
    assert "rozpočet" in printed
    assert not (out / "T3.json").exists()
    assert (out / "T1.json").exists() and (out / "T11.json").exists()
    # every charge cap fits into what was left: committed so far (worst-case estimates) + cap <= budget
    worst = {ACT_IG_SEARCH: 0.108, ACT_NEWS: 0.04}
    committed = 0.0
    for c in runner.calls:
        assert 0 < c["max_usd"] and committed + c["max_usd"] <= budget + 1e-9
        committed += worst[c["actor"]]
    assert committed <= budget


def test_budget_guard_counts_reported_usage_above_estimate(fake_token, capsys):
    """A run that uses its whole cap (above the estimate) eats the budget for the next tests."""
    runner = FakeRunner(usd="cap")
    rc = lt.main(["--yes", "--only", "T10,T11", "--budget", "0.12"], runner=runner)
    assert rc == 0
    # T10 (worst 0.018) runs and uses its cap 0.09; T11 (worst 0.04) no longer fits into the 0.03 left.
    assert [c["actor"] for c in runner.calls] == [ACT_TT_PROFILE]
    assert runner.calls[0]["max_usd"] <= 0.12
    assert "rozpočet" in capsys.readouterr().out


def test_every_run_gets_charge_cap_and_max_items(full_run):
    calls = full_run["runner"].calls
    assert full_run["rc"] == 0
    assert {c["actor"] for c in calls} >= {ACT_IG_SEARCH, ACT_IG_HASHTAG, ACT_IG_SCRAPER, ACT_IG_PROFILE, ACT_IG_POST,
                                           ACT_IG_COMMENT, ACT_BRAND, ACT_TT, ACT_TT_PROFILE, ACT_NEWS, lt.ACT_YT}
    for c in calls:
        assert c["max_items"] >= 1 and c["max_usd"] > 0
        if c["actor"] == ACT_TT:
            assert c["max_usd"] >= 0.5          # tiktok-scraper minimalMaxTotalChargeUsd
    assert sum(1 for c in calls if c["actor"] == ACT_IG_POST) == 1
    post = next(c for c in calls if c["actor"] == ACT_IG_POST)
    assert post["input"]["dataDetailLevel"] == "detailedData"
    assert len(calls) == 18                                # T1..T12: 2+2+1+3+1+1+1+2+2+1+1+1 runs


def test_dependent_inputs_come_from_earlier_tests(full_run):
    calls = full_run["runner"].calls
    prof = next(c for c in calls if c["actor"] == ACT_IG_PROFILE)["input"]["usernames"]
    assert prof[0] == "kamvbrne"
    assert "sample_cukrarka_brno" in prof and "sample_foodie_brno" in prof     # from T1 and T3
    assert "sample_teen_baker" not in prof                                     # bio-stated minor never forwarded
    post = next(c for c in calls if c["actor"] == ACT_IG_POST)["input"]["username"]
    assert "https://www.instagram.com/p/SAMPLEh1/" in post and post[-1] == "kamvbrne"   # T3 #spoluprace
    places = [c["input"]["directUrls"][0] for c in calls if c["actor"] == ACT_IG_SCRAPER]
    assert places[0].endswith("/100000001/")                                   # Brno place from T2 (in CITY_BBOX)


# ---------------------------------------------------------------------------------------------
# Privacy: saved data and report
# ---------------------------------------------------------------------------------------------

_PERSONAL_KEYS = {"caption", "text", "biography", "signature", "fullName", "full_name", "ownerFullName",
                  "firstComment", "title", "description", "name", "channelName", "address"}


def _personal_strings() -> set[str]:
    out: set[str] = set()

    def walk(x, parent_key=None):
        if isinstance(x, dict):
            for k, v in x.items():
                if k in _PERSONAL_KEYS and isinstance(v, str):
                    out.add(v)
                walk(v, k)
        elif isinstance(x, list):
            for v in x:
                walk(v, parent_key)

    for f in SAMPLES.glob("*.json"):
        walk(json.loads(f.read_text("utf-8"))["items"])
    walk(YT_ITEMS)
    commenters = [c for it in sample("ig_posts_detailed.json") for c in it.get("latestComments") or []]
    commenters += sample("ig_comments.json")
    out.update(c["ownerUsername"] for c in commenters if isinstance(c.get("ownerUsername"), str))
    return {x.strip() for x in out if len(x.strip()) >= 5}


def test_report_contains_no_captions_comments_or_names(full_run):
    report = full_run["report"]
    assert report
    forbidden = _personal_strings()
    assert "real.person.should.vanish" in forbidden and "Vypadá skvěle! @kamaradka_sample" in forbidden
    leaked = sorted(x for x in forbidden if x in report)
    assert not leaked, leaked
    for x in forbidden:   # also not in the console output
        assert x not in full_run["stdout"], x


def test_report_has_verdicts_verify_items_and_mapper_stats(full_run):
    report = full_run["report"]
    for k in lt.TEST_KEYS:
        assert f"## {k}." in report, k
    assert "## Souhrn" in report and "## Co z toho plyne pro provider" in report
    assert "**Verdikt: " in report and "### VERIFY LIVE" in report
    assert "`map_ig_profile` → Profile" in report and "`map_ig_post` → Post" in report
    assert "`map_tt_video` → Post" in report and "`map_news` → NewsItem" in report
    assert "nenamapováno" in report                      # sample error items show up as not mapped, with a reason
    assert "## T12." in report and "isPaidContent" in report
    t12 = report.split("## T12.")[1]
    assert "**Verdikt: PASS**" in t12                     # first video true, second false


def test_saved_data_has_commenter_identity_redacted(full_run):
    out = full_run["out"]
    t6 = (out / "T6.json").read_text("utf-8")
    t7 = (out / "T7.json").read_text("utf-8")
    for name in ("real.person.should.vanish", "another.person", "https://x/pic.jpg"):
        assert name not in t6 and name not in t7
    d6 = json.loads(t6)
    comments = [c for it in d6["runs"][0]["items"] for c in it.get("latestComments") or []]
    assert comments and all(c.get("ownerUsername") == lt.REDACTED for c in comments if "ownerUsername" in c)
    assert any("text" in c for c in comments)            # keys stay so the shape is visible (VERIFY LIVE 10)
    t1 = json.loads((out / "T1.json").read_text("utf-8"))
    assert any("_redacted" in it for r in t1["runs"] for it in r["items"])   # sample_teen_baker dropped
    assert "sample_teen_baker" not in json.dumps(t1)
    assert "purge" in full_run["stdout"]                 # reminder printed


def test_t7_skipped_when_t6_returned_latest_comments(fake_token, capsys):
    runner = FakeRunner()
    rc = lt.main(["--yes", "--only", "T3,T5,T6,T7"], runner=runner)
    assert rc == 0
    assert ACT_IG_COMMENT not in {c["actor"] for c in runner.calls}
    assert "latestComments" in capsys.readouterr().out


def test_scrub_keeps_shape_and_drops_identity():
    items = lt.scrub_items(ACT_IG_COMMENT, sample("ig_comments.json"))
    assert items[0]["ownerUsername"] == lt.REDACTED and items[0]["owner"] == lt.REDACTED
    assert items[0]["text"]                               # raw text stays in the local file (not in the report)
    assert items[-1].get("error") == "not_found"          # error items untouched


def test_concurrent_mode_respects_dependencies(fake_token, capsys):
    runner = FakeRunner()
    rc = lt.main(["--yes", "--force-t7", "--concurrency", "9"], runner=runner)
    assert rc == 0
    assert "omezeno na 1 až 5" in capsys.readouterr().err
    actors = [c["actor"] for c in runner.calls]
    assert len(actors) == 18
    # T5 is built only after T1 and T3 finished: its usernames come from their output
    prof = next(c for c in runner.calls if c["actor"] == ACT_IG_PROFILE)["input"]["usernames"]
    assert "sample_cukrarka_brno" in prof and "sample_foodie_brno" in prof


def test_mapper_analysis_flags_fields_lost_in_mapping():
    """A raw value the mapper does not read (a TikTok authorMeta.name without nickName, VERIFY LIVE 15) is
    reported as lost."""
    from datetime import datetime, timezone

    from app.sources import apify_provider as ap

    vids = sample("tt_profile_videos.json")
    for v in vids:
        if isinstance(v.get("authorMeta"), dict):
            v["authorMeta"].pop("nickName", None)
            v["authorMeta"]["name"] = "Sample Nick"
    st, objs = lt.map_group("map_tt_profiles", "Profile", vids,
                            lambda xs: ap.map_tt_profiles(xs, actor=ACT_TT_PROFILE,
                                                          fetched_at=datetime(2026, 10, 9, tzinfo=timezone.utc)))
    assert objs and st.lost["display_name ← authorMeta.name"] >= 1
    line = lt.mapper_lines([st], "")[0]
    assert "ztraceno při mapování" in line and "Sample Nick" not in line


def test_foreign_files_are_never_overwritten_or_purged(fake_token, capsys):
    """Another session saves raw lists as data/live-tests/T5.json etc.: the script writes beside them."""
    out = default_out()
    out.mkdir(parents=True)
    foreign = out / "T11.json"
    foreign.write_text('[{"title": "foreign raw list"}]', "utf-8")
    (out / "report.md").write_text("# someone else's notes\n", "utf-8")
    rc = lt.main(["--yes", "--only", "T11"], runner=FakeRunner())
    assert rc == 0
    assert foreign.read_text("utf-8") == '[{"title": "foreign raw list"}]'
    assert (out / "T11.live_tests.json").exists() and lt.is_ours(out / "T11.live_tests.json")
    assert (out / "report.md").read_text("utf-8") == "# someone else's notes\n"
    assert (out / "report.live_tests.md").read_text("utf-8").startswith(lt.REPORT_TITLE)
    assert lt.load_saved(out, "T11")["test"] == "T11"
    capsys.readouterr()
    assert lt.main(["--purge", "--yes"]) == 0
    assert foreign.exists() and (out / "report.md").exists()
    assert not (out / "T11.live_tests.json").exists() and not (out / "report.live_tests.md").exists()
    assert "T11.json" in capsys.readouterr().out          # listed as left in place


# ---------------------------------------------------------------------------------------------
# Review fixes: no run without a charge cap, no paying twice, raw IG shape redacted, --out, post URLs
# ---------------------------------------------------------------------------------------------


def test_live_refused_when_client_cannot_send_charge_cap(fake_token, monkeypatch, capsys):
    """Only max_total_charge_usd bounds cost (max_items does not): without it nothing starts."""
    monkeypatch.setattr(lt, "client_info", lambda: {"version": "0.9", "max_total_charge_usd": False, "max_items": True})
    runner = FakeRunner()
    rc = lt.main(["--yes", "--only", "T11"], runner=runner)
    assert rc == 2 and runner.calls == []
    assert "max_total_charge_usd" in capsys.readouterr().err
    assert not default_out().exists()
    # the dry run still works and says so
    assert lt.main(["--dry-run", "--only", "T11"], runner=NeverRunner()) == 0
    assert "živý běh se proto nespustí" in capsys.readouterr().out


def test_run_that_raised_is_not_started_again(fake_token, capsys):
    """An error after the run started (waiting, reading the dataset) must not lead to a second paid run."""
    runner = ScriptedRunner(RuntimeError("dataset read failed after the run finished"))
    rc = lt.main(["--yes", "--only", "T11", "--budget", "1"], runner=runner)
    printed = capsys.readouterr().out
    assert rc == 0 and len(runner.calls) == 1
    assert "Znovu nespouštím" in printed and "Apify Console" in printed
    rec = lt.load_saved(default_out(), "T11")["runs"][0]
    assert rec["status"] == "ERROR" and rec["attempts"] == 1 and "dataset read failed" in rec["error"]
    # the whole cap counted against the budget
    assert f"do rozpočtu započteno {runner.calls[0]['max_usd']:.3f} z 1.00 USD" in printed


def test_failed_run_without_items_is_retried_once_and_both_costs_count(fake_token, capsys):
    runner = ScriptedRunner(
        RunResult(items=[], status="FAILED", usd=0.011, events={"result": 0, "actor-start": 1}, run_id="r1"),
        RunResult(items=items_for(ACT_NEWS, {}), status="SUCCEEDED", usd=0.02, events={"result": 5}, run_id="r2"))
    rc = lt.main(["--yes", "--only", "T11"], runner=runner)
    assert rc == 0 and len(runner.calls) == 2
    assert "FAILED bez dat; zkouším znovu" in capsys.readouterr().out
    rec = lt.load_saved(default_out(), "T11")["runs"][0]
    assert rec["attempts"] == 2 and rec["run_ids"] == ["r1", "r2"] and rec["run_id"] == "r2"
    assert rec["usage_total_usd"] == pytest.approx(0.031)
    assert rec["charged_event_counts"] == {"result": 5, "actor-start": 1}


def test_budget_counts_items_when_reported_usage_is_stale(fake_token, capsys):
    """call() often returns usageTotalUsd before the charges settle (0.0): items x price still counts."""
    many = [dict(it, url=f"https://example.cz/{i}") for i, it in enumerate(items_for(ACT_NEWS, {}) * 30)]
    runner = ScriptedRunner(RunResult(items=many, status="SUCCEEDED", usd=0.0, run_id="r1"))
    assert lt.main(["--yes", "--only", "T11"], runner=runner) == 0
    printed = capsys.readouterr().out
    spent = float(re.search(r"do rozpočtu započteno (\d+\.\d+)", printed).group(1))
    assert spent == pytest.approx(len(many) * 0.004, abs=0.002) and spent > 0.04


def test_saved_test_is_skipped_and_rerun_keeps_the_old_data(fake_token, capsys):
    out = default_out()
    runner = FakeRunner()
    assert lt.main(["--yes", "--only", "T11"], runner=runner) == 0
    first = lt.load_saved(out, "T11")
    assert len(runner.calls) == 1 and first
    capsys.readouterr()
    # again without --rerun: nothing runs, nothing is overwritten
    assert lt.main(["--yes", "--only", "T11"], runner=runner) == 0
    printed = capsys.readouterr().out
    assert len(runner.calls) == 1
    assert "data už jsou uložená" in printed and first["saved_at"] in printed and "Nic ke spuštění" in printed
    assert lt.load_saved(out, "T11")["saved_at"] == first["saved_at"]
    assert lt.main(["--dry-run", "--only", "T11"], runner=NeverRunner()) == 0
    assert "přeskočí se: data už jsou uložená" in capsys.readouterr().out
    # --rerun: runs again, the previous file moves to T11.<UTC timestamp>.json
    assert lt.main(["--yes", "--only", "T11", "--rerun"], runner=runner) == 0
    assert len(runner.calls) == 2
    archived = [p for p in out.glob("T11.*.json") if re.fullmatch(r"T11\.\d{8}T\d{6}Z\.json", p.name)]
    assert len(archived) == 1 and lt.is_ours(archived[0])
    assert json.loads(archived[0].read_text("utf-8"))["saved_at"] == first["saved_at"]
    assert lt.load_saved(out, "T11")["saved_at"] != first["saved_at"]
    capsys.readouterr()
    assert lt.main(["--purge", "--yes"]) == 0          # archived files are this script's too
    assert not list(out.glob("T11*.json")) if out.exists() else True


def test_raw_instagram_usertags_comments_and_likers_are_redacted():
    """instagram-scraper place items (T2 / T4) carry Instagram's raw post shape."""
    item = {"location_id": "100000001", "name": "Sample Place", "posts": [{
        "user": {"username": "sample_poster", "full_name": "Sample Poster Name"},
        "usertags": {"in": [{"position": [0.1, 0.2], "user": {
            "username": "sample_tagged", "full_name": "Tagged Stranger Name", "profile_pic_url": "https://x/tag.jpg"}}]},
        "carousel_media": [{"usertags": {"in": [{"user": {
            "username": "sample_tagged2", "full_name": "Carousel Stranger Name", "profile_pic_url": "https://x/c.jpg"}}]}}],
        "preview_comments": [{"pk": "1789", "text": "Sample comment text", "user": {
            "username": "sample_commenter_x", "full_name": "Commenter Person Name"}}],
        "facepile_top_likers": [{"pk": "42", "username": "sample_liker_x", "full_name": "Liker Person Name",
                                 "profile_pic_url": "https://x/l.jpg"}],
    }]}
    [out] = lt.scrub_items(ACT_IG_SCRAPER, [item])
    dumped = json.dumps(out, ensure_ascii=False)
    for gone in ("Tagged Stranger Name", "https://x/tag.jpg", "Carousel Stranger Name", "https://x/c.jpg",
                 "sample_commenter_x", "Commenter Person Name", "sample_liker_x", "Liker Person Name", "https://x/l.jpg"):
        assert gone not in dumped, gone
    post = out["posts"][0]
    assert post["usertags"]["in"][0]["user"] == {"username": "sample_tagged", "full_name": lt.REDACTED,
                                                 "profile_pic_url": lt.REDACTED}       # shape and handle stay
    assert post["preview_comments"][0]["text"] == "Sample comment text"
    assert post["user"]["full_name"] == "Sample Poster Name"                          # the post's author stays
    assert item["posts"][0]["usertags"]["in"][0]["user"]["full_name"] == "Tagged Stranger Name"   # input untouched


def test_out_must_stay_inside_data_live_tests(capsys):
    for bad in (lt.BACKEND_DIR / "tests" / "apify_samples", lt.REPO_DIR / "docs", default_out().parent,
                default_out() / ".." / "elsewhere"):
        assert lt.main(["--dry-run", "--out", str(bad)], runner=NeverRunner()) == 2, bad
        assert "--out musí ležet uvnitř" in capsys.readouterr().err
    assert lt.main(["--report-only", "--out", str(default_out() / "druhy-pokus")]) == 0
    assert (default_out() / "druhy-pokus" / "report.md").exists()


def test_post_url_options_reject_profile_urls(capsys):
    assert lt.main(["--dry-run", "--t6-post-urls", "https://www.instagram.com/p/SAMPLEh1/,https://www.instagram.com/kamvbrne/"],
                   runner=NeverRunner()) == 2
    err = capsys.readouterr().err
    assert "--t6-post-urls" in err and "instagram.com/kamvbrne/" in err
    assert lt.main(["--dry-run", "--t7-post-urls", "kamvbrne"], runner=NeverRunner()) == 2
    capsys.readouterr()
    assert lt.main(["--dry-run", "--only", "T6", "--t6-post-urls", "https://www.instagram.com/reel/SAMPLEr1/"],
                   runner=NeverRunner()) == 0
    assert "SAMPLEr1" in capsys.readouterr().out
