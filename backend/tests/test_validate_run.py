"""scripts/validate_run.py: the automatic checks A0-A7 of docs/validation-plan.md on a made-up run and a
made-up cache dir (no real people, no network except a local stub server on 127.0.0.1:8040-8049)."""

from __future__ import annotations

import copy
import importlib.util
import json
import socket
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts" / "validate_run.py"


def _load():
    spec = importlib.util.spec_from_file_location("creator_scout_validate_run", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod          # dataclasses resolve annotations through sys.modules
    spec.loader.exec_module(mod)
    return mod


V = _load()


@pytest.fixture
def fixture(tmp_path):
    run, cache = V.synthetic_fixture()
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    for i, data in enumerate(cache):
        (cache_dir / f"c{i}.json").write_text(json.dumps(data, ensure_ascii=False), "utf-8")
    run_file = tmp_path / "run.json"
    run_file.write_text(json.dumps(run, ensure_ascii=False), "utf-8")
    return run, cache_dir, run_file


def _idx(cache_dir):
    return V.build_index([str(cache_dir)])


def _by(checks, cid):
    return next(c for c in checks if c.id == cid)


# ------------------------------------------------------------------------------------------ clean run


def test_clean_synthetic_run_passes_everything(fixture, capsys):
    _run, cache_dir, run_file = fixture
    code = V.main(["--file", str(run_file), "--cache-dir", str(cache_dir), "--self-test"])
    out = capsys.readouterr().out
    assert code == 0, out
    assert out.startswith("| Check | Sample size | Result | Pass/fail |\n|---|---|---|---|\n")
    for cid in ("A0", "A1", "A2", "A3", "A5a", "A6", "A7"):
        row = next(line for line in out.splitlines() if line.startswith(f"| {cid} "))
        assert row.endswith("| pass |"), row
    assert "| A4 " in out and "not run (needs --diff)" in out
    assert "| A5b Wrong anchor not matched | - | no wrong-anchor run given | skipped |" in out
    assert "example_baker" not in out and "example_small" not in out      # no handles in the output
    assert "subject-mode branch not merged" in out          # SM1-SM3 skipped with a note


def test_quote_classes(fixture):
    run, cache_dir, _ = fixture
    idx, n_files = _idx(cache_dir)
    assert n_files == 1
    chk = V.a2_quotes([run], idx, n_files)
    assert chk.status == V.PASS
    assert chk.details["classes"]["found"] >= 3
    assert chk.details["classes"]["label_not_quote"] == 1    # "search:pekárna brno"
    assert V.classify_quote("https://www.instagram.com/p/EXAMPLE1/", "#brnofood", idx) == "found"   # in the caption
    assert V.classify_quote("https://www.instagram.com/p/EXAMPLE2/", "#brnofood", {}) == "label_not_quote"
    # clipped quote with a trailing ellipsis and newlines collapsed still counts as found
    bio = run["candidates"]["instagram:example_baker"]["report"]["findings"][0]["sources"][0]["quote"]
    assert V.classify_quote("https://www.instagram.com/example_baker", bio[:30] + "…", idx) == "found"
    assert V.classify_quote("https://www.instagram.com/example_baker/", "📍 Veveří 12", idx) == "found"
    assert V.classify_quote("https://www.instagram.com/p/EXAMPLE1/", "@EXAMPLE1", idx) == "found_in_url"
    assert V.classify_quote("https://example.test/unknown", "some text nobody fetched", idx) == "unresolved"
    assert V.classify_quote("https://www.instagram.com/example_baker/", "Placené partnerství s X (Meta Branded Content)",
                            idx) == "label_not_quote"
    assert V.classify_quote("https://www.instagram.com/example_baker/", "words that are not in the bio", idx) == "not_found"


def test_a2_skipped_without_cache_dir(fixture):
    run, _, _ = fixture
    assert V.a2_quotes([run], {}, 0).status == V.SKIP


# ------------------------------------------------------------------------------------------ A0


def test_selftest_on_builtin_run_finds_3_of_3(capsys):
    assert V.main(["--self-test"]) == 0
    out = capsys.readouterr().out
    assert "| A0 Checker finds planted defects | 3 planted defects in a copy of r_selftest | 3 of 3 found | pass |" in out


def test_selftest_uses_a_given_run_when_it_can(fixture):
    run, cache_dir, _ = fixture
    run = copy.deepcopy(run)
    run["id"] = "r_given"
    idx, _ = _idx(cache_dir)
    chk = V.selftest([run], idx)
    assert chk.status == V.PASS and chk.details["base_run"] == "r_given"
    assert run["candidates"]["instagram:example_baker"]["report"]["findings"][0]["sources"]   # original untouched


def test_selftest_falls_back_when_run_has_no_eliminations(fixture):
    run, cache_dir, _ = fixture
    run = copy.deepcopy(run)
    del run["candidates"]["instagram:example_small"]
    chk = V.selftest([run], _idx(cache_dir)[0])
    assert chk.status == V.PASS and chk.details["base_run"] == "r_selftest"


# ------------------------------------------------------------------------------------------ single defects


def test_a1_flags_fact_without_source_and_bad_inference(fixture):
    run, _, _ = fixture
    run = copy.deepcopy(run)
    findings = run["candidates"]["instagram:example_baker"]["report"]["findings"]
    findings[0]["sources"] = [{**findings[1]["sources"][0], "url": "not-a-url"}]
    findings[2]["based_on"] = ["g:audience"]          # an inference must rest on facts
    chk = V.a1_sources([run])
    assert chk.status == V.FAIL
    assert any(x.endswith("f:followers:no_source") for x in chk.details["failed"])
    assert any(x.endswith("i:local:based_on") for x in chk.details["failed"])


def test_a1_claims_need_quoted_source_and_known_evidence(fixture):
    run, _, _ = fixture
    run = copy.deepcopy(run)
    rep = run["candidates"]["instagram:example_baker"]["report"]
    src = copy.deepcopy(rep["findings"][1]["sources"][0])
    rep["claims"] = [{"id": "c:1", "claim": "x", "claim_source": {**src, "quote": ""}, "evidence": ["f:missing"],
                      "status": "supported", "confidence": "low", "note": {"cs": "", "en": ""}}]
    failed = V.a1_sources([run]).details["failed"]
    assert any(x.endswith("c:1:claim_source") for x in failed) and any(x.endswith("c:1:evidence") for x in failed)


def test_a2_altered_quote_on_fact_fails_but_elsewhere_only_reported(fixture):
    run, cache_dir, _ = fixture
    idx, n = _idx(cache_dir)
    bad = copy.deepcopy(run)
    src = bad["candidates"]["instagram:example_baker"]["report"]["findings"][1]["sources"][0]
    src["quote"] = src["quote"][:-6] + "XXXXXX"
    assert V.a2_quotes([bad], idx, n).status == V.FAIL
    other = copy.deepcopy(run)
    res = other["candidates"]["instagram:example_baker"]["results"][0]["sources"][0]
    res["quote"] = "text that is nowhere in the fetched bio"
    chk = V.a2_quotes([other], idx, n)
    assert chk.status == V.PASS and len(chk.details["not_found_other"]) == 1


@pytest.mark.parametrize("change, problem", [
    (lambda c: c["results"][0].update(status="unknown"), "result_fail"),   # missing data never eliminates
    (lambda c: c["results"][0].update(value=""), "value"),
    (lambda c: c["results"][0].update(threshold=""), "threshold"),
    (lambda c: c["elimination"].update(round=7), "round"),
    (lambda c: c["elimination"].update(sources=[]), "source"),
    (lambda c: c["elimination"].update(reason={"cs": "x", "en": ""}), "reason_en"),
    (lambda c: c["elimination"].update(criterion_id="other"), "result"),
])
def test_a3_elimination_defects(fixture, change, problem):
    run, _, _ = fixture
    run = copy.deepcopy(run)
    change(run["candidates"]["instagram:example_small"])
    chk = V.a3_eliminations([run])
    assert chk.status == V.FAIL and problem in chk.details["failed"][0].split(":")[-1].split("+")


def test_a5_identity(fixture):
    run, _, _ = fixture
    run = copy.deepcopy(run)
    rep = run["candidates"]["instagram:example_baker"]["report"]
    rep["identity"][0]["signals"][0]["source"] = None
    failed = V.a5_identity([run]).details["failed"][0]
    assert failed.endswith("matched_without_source") and "example_baker" not in failed
    rep["identity"] = []
    chk = V.a5_identity([run])
    assert chk.status == V.FAIL and chk.details["failed"][0].endswith("no_identity_verdict")
    rep["identity_verdict"] = {"status": "uncertain", "text": {"cs": "x", "en": "Not sure"}}
    chk = V.a5_identity([run])
    assert chk.status == V.PASS and chk.id == "A5a" and chk.sample == "1 reports (1 unique candidate)"


def test_a5_wrong_anchor_run(fixture):
    run, _, _ = fixture
    wrong = copy.deepcopy(run)
    rep = wrong["candidates"]["instagram:example_baker"]["report"]
    rep["identity_verdict"] = {"status": "confirmed", "text": {"en": "We are confident"}, "supporting": []}
    chk = V.a5b_wrong_anchor([wrong])
    assert chk.status == V.FAIL and any("WRONG_ANCHOR_ACCEPTED" in x for x in chk.details["failed"])
    rep["identity_verdict"] = {"status": "uncertain", "text": {"en": "The anchor city Praha is not on the profile"},
                               "contradicting": [{"signal": "city", "supports": False, "source": None}]}
    assert V.a5b_wrong_anchor([wrong]).status == V.PASS
    rep["identity_verdict"] = {"status": "uncertain", "text": {"en": "Not sure"}}     # mismatch not named
    assert V.a5b_wrong_anchor([wrong]).status == V.FAIL


def test_a6_unlabeled_source(fixture):
    run, _, _ = fixture
    run = copy.deepcopy(run)
    del run["candidates"]["instagram:example_small"]["elimination"]["sources"][0]["mode"]
    run["candidates"]["instagram:example_small"]["results"][0]["sources"][0]["mode"] = "apify"
    chk = V.a6_labels([run])
    assert chk.status == V.FAIL and len(chk.details["failed"]) == 2


def test_a7_score_keys_in_run(fixture):
    run, cache_dir, _ = fixture
    run = copy.deepcopy(run)
    run["candidates"]["instagram:example_baker"]["overall_score"] = 8
    run["candidates"]["instagram:example_small"]["metrics"] = {"best_fit": True, "age": 31}
    chk = V.a7_hard_lines([run], [str(cache_dir)])
    assert chk.status == V.FAIL and len(chk.details["score_keys"]) == 3


def test_a7_commenter_identity_in_cache(fixture, tmp_path):
    run, cache_dir, _ = fixture
    comments = {"meta": {"provider": "apify", "method": "comments"},
                "items": [{"post_url": "https://www.instagram.com/p/EXAMPLE1/", "text": "super", "source": None,
                           "ownerUsername": "someone"}]}
    (cache_dir / "comments.json").write_text(json.dumps(comments), "utf-8")
    raw = [{"url": "https://www.instagram.com/p/EXAMPLE1/", "caption": "x",
            "latestComments": [{"text": "a", "owner": {"username": "[redacted]"}},     # redacted: fine
                               {"text": "b", "owner": {"username": "realperson"}}]}]
    (cache_dir / "raw.json").write_text(json.dumps(raw), "utf-8")
    chk = V.a7_hard_lines([run], [str(cache_dir)])
    assert chk.status == V.FAIL
    hits = chk.details["commenter_identity"]
    assert len(hits) == 2 and any("ownerUsername" in h for h in hits) and any("latestComments.1.owner" in h for h in hits)


def test_a7_clean_comments_pass(fixture):
    run, cache_dir, _ = fixture
    comments = {"meta": {"method": "comments"}, "items": [
        {"post_url": "https://www.instagram.com/p/EXAMPLE1/", "text": "super", "created_at": None, "source": None}]}
    (cache_dir / "comments.json").write_text(json.dumps(comments), "utf-8")
    chk = V.a7_hard_lines([run], [str(cache_dir)])
    assert chk.status == V.PASS and "1 stored comments" in chk.sample


# ------------------------------------------------------------------------------------------ A4


def _switched(run):
    after = copy.deepcopy(run)
    cand = after["candidates"]["instagram:example_baker"]
    cand["report"]["findings"][1]["text"]["en"] = "Posts about protein bars"
    cand["report"]["questions"] = [{"cs": "?", "en": "Do you train at a gym?"}]
    cand["results"][0]["status"] = "fail"
    return after


def test_a4_two_snapshots(fixture, tmp_path):
    run, _, _ = fixture
    a, b = tmp_path / "a.json", tmp_path / "b.json"
    a.write_text(json.dumps(run), "utf-8")
    b.write_text(json.dumps(_switched(run)), "utf-8")
    chk = V.a4_goal([str(a), str(b)])
    assert chk.status == V.PASS
    assert "1 findings, 2 questions, 0 claim statuses, 0 competitor flags, 1 criterion results" in chk.result
    assert "live fetches during switch 0" in chk.result
    assert chk.details["facts_changed_text"] == 1


def test_a4_fails_without_changes_or_with_live_fetch(fixture, tmp_path):
    run, _, _ = fixture
    a, b = tmp_path / "a.json", tmp_path / "b.json"
    a.write_text(json.dumps(run), "utf-8")
    b.write_text(json.dumps(run), "utf-8")
    assert V.a4_goal([str(a), str(b)]).status == V.FAIL
    after = _switched(run)
    after["log"] = [{"ts": "t", "text": "fetch", "mode": "live"}]
    b.write_text(json.dumps(after), "utf-8")
    chk = V.a4_goal([str(a), str(b)])
    assert chk.status == V.FAIL and chk.details["live_fetches"] == 1


def test_a4_from_report_diff(tmp_path):
    f = tmp_path / "goal.json"
    f.write_text(json.dumps({"report_diffs": [{"candidate_id": "x", "added": ["i:competitor"], "removed": [],
                                               "moved_up": ["f:collab"], "questions_added": [{"en": "q"}],
                                               "checks_changed": [{"criterion_id": "topic_share"}],
                                               "summary": {"en": "changed"}}]}), "utf-8")
    chk = V.a4_goal([str(f)])
    assert chk.status == V.PASS_NO_LIVE and "2 findings, 1 questions" in chk.result
    f.write_text(json.dumps({"report_diffs": []}), "utf-8")
    assert V.a4_goal([str(f)]).status == V.FAIL


# ------------------------------------------------------------------------------------------ subject mode


def test_subject_mode_checks_run_when_fields_exist(fixture):
    run, _, _ = fixture
    run = copy.deepcopy(run)
    rep = run["candidates"]["instagram:example_baker"]["report"]
    for f in rep["findings"]:
        f["confidence"], f["confidence_basis"] = "high", {"cs": "x", "en": "platform profile data"}
    rep["identity_verdict"] = {"status": "confirmed", "text": {"en": "We are confident"},
                               "supporting": rep["identity"][0]["signals"]}
    rep["last_diff"] = {"candidate_id": "x", "added": ["f:post"], "removed": ["f:gone"], "summary": {"en": "x"}}
    checks = {c.id: c for c in V.subject_checks([run])}
    assert [checks[k].status for k in ("SM1", "SM2", "SM3")] == [V.PASS] * 3
    rep["findings"][3]["confidence"] = None
    rep["last_diff"]["removed"] = ["f:post"]
    checks = {c.id: c for c in V.subject_checks([run])}
    assert checks["SM1"].status == V.FAIL and checks["SM3"].status == V.FAIL


# ------------------------------------------------------------------------------------------ CLI


def test_exit_code_1_and_details_on_failure(fixture, tmp_path, capsys, monkeypatch):
    run, cache_dir, _ = fixture
    run = copy.deepcopy(run)
    run["candidates"]["instagram:example_baker"]["report"]["identity"] = []
    f = tmp_path / "bad.json"
    f.write_text(json.dumps(run), "utf-8")
    monkeypatch.setattr(V, "VALIDATION_DIR", tmp_path / "validation")
    assert V.main(["--file", str(f), "--cache-dir", str(cache_dir), "--json", "out.json"]) == 1
    out = capsys.readouterr().out
    assert "| A5a Identity verdict present | 1 reports (1 unique candidate) |" in out and "| FAIL |" in out
    assert "A5a failures (1" in out
    written = (tmp_path / "validation" / "out.json").read_text()
    assert json.loads(written)[0]["id"] == "A1" and "example_baker" not in written


def test_usage_errors():
    with pytest.raises(SystemExit) as e:
        V.main([])
    assert e.value.code == 2
    with pytest.raises(SystemExit):
        V.main(["--run", "r_x"])          # --run without --base


def _free_port() -> int:
    for port in range(8040, 8050):
        with socket.socket() as s:
            try:
                s.bind(("127.0.0.1", port))
                return port
            except OSError:
                continue
    pytest.skip("no free port in 8040-8049")


def test_base_url_with_run_and_all_runs(fixture, capsys):
    run, cache_dir, _ = fixture
    other = copy.deepcopy(run)
    other["id"] = "r_other"
    runs = {run["id"]: run, other["id"]: other}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            if self.path == "/api/runs":
                body = [{"run_id": k} for k in runs]
            elif self.path.startswith("/api/runs/") and self.path.split("/")[-1] in runs:
                body = runs[self.path.split("/")[-1]]
            else:
                self.send_response(404)
                self.end_headers()
                return
            data = json.dumps(body).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, *args):
            pass

    server = HTTPServer(("127.0.0.1", _free_port()), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        assert V.main(["--base", base, "--run", "r_selftest", "--cache-dir", str(cache_dir)]) == 0
        assert "Runs: r_selftest (2 unique candidates)." in capsys.readouterr().out
        assert V.main(["--base", base, "--all-runs", "--cache-dir", str(cache_dir)]) == 0
        out = capsys.readouterr().out
        assert "Runs: r_selftest, r_other (2 unique candidates)." in out
        assert V.main(["--base", base, "--run", "r_missing"]) == 2   # 404 -> load error, not a failed check
    finally:
        server.shutdown()
        server.server_close()


# ------------------------------------------------------------------------------------------ review fixes


def test_empty_run_measures_nothing_and_exits_1(tmp_path, capsys):
    f = tmp_path / "empty.json"
    f.write_text(json.dumps({"id": "r_empty", "criteria": {}, "candidates": {}}), "utf-8")
    assert V.main(["--file", str(f)]) == 1
    out = capsys.readouterr().out
    assert "nothing measured" in out
    assert next(line for line in out.splitlines() if line.startswith("| A7 ")).endswith("| skipped |")


def test_a3_eliminated_without_record(fixture):
    run, _, _ = fixture
    run = copy.deepcopy(run)
    run["candidates"]["instagram:example_small"]["elimination"] = None
    chk = V.a3_eliminations([run])
    assert chk.status == V.FAIL and chk.details["failed"][0].endswith("no_elimination_record")
    assert "example_small" not in chk.details["failed"][0]


def test_a2_wrong_cache_dir_is_skipped_not_passed(fixture, tmp_path):
    run, _, _ = fixture
    other = tmp_path / "other"
    other.mkdir()
    (other / "x.json").write_text(json.dumps({"meta": {}, "items": [
        {"url": "https://example.test/unrelated", "caption": "nothing here"}]}), "utf-8")
    idx, n = V.build_index([str(other)])
    chk = V.a2_quotes([run], idx, n)
    assert chk.status == V.SKIP and chk.result.startswith("0 quotes resolved, check --cache-dir")
    assert "on facts, claims and eliminations: 0 not found, 3 unresolved" in chk.result


def test_a2_output_hides_quote_text_unless_show_text(fixture, capsys):
    run, cache_dir, _ = fixture
    idx, n = _idx(cache_dir)
    bad = copy.deepcopy(run)
    src = bad["candidates"]["instagram:example_baker"]["report"]["findings"][1]["sources"][0]
    src["quote"] = "Secret caption words that were never fetched"
    chk = V.a2_quotes([bad], idx, n)
    entry = chk.details["failed"][0]
    assert chk.status == V.FAIL and "quote" not in entry and entry["quote_len"] == len(src["quote"])
    text = V.details_text([chk])
    assert "Secret caption" not in text and "example_baker" not in text and "EXAMPLE1" not in text
    V.SHOW_TEXT = True
    try:
        assert "Secret caption" in V.details_text([V.a2_quotes([bad], idx, n)])
    finally:
        V.SHOW_TEXT = False


@pytest.mark.parametrize("identity, ok", [
    ([], False),                                                                      # empty list
    ([{"platform": "tiktok", "handle": "x", "status": "matched",
       "signals": [{"signal": "bio", "supports": True, "source": None}]}], False),     # matched
    ([{"platform": "tiktok", "handle": "x", "status": "uncertain",
       "signals": [{"signal": "bio", "supports": True, "source": None}]}], False),     # nothing speaks against
    ([{"platform": "tiktok", "handle": "x", "status": "rejected",
       "signals": [{"signal": "city", "supports": False, "source": None}]}], True),
])
def test_a5b_identity_list_branch(fixture, identity, ok):
    run, _, _ = fixture
    wrong = copy.deepcopy(run)
    wrong["candidates"]["instagram:example_baker"]["report"]["identity"] = identity
    assert V.a5b_wrong_anchor([wrong]).status == (V.PASS if ok else V.FAIL)


def test_a5b_wrong_anchor_run_without_report_fails(fixture):
    run, _, _ = fixture
    wrong = copy.deepcopy(run)
    wrong["candidates"]["instagram:example_baker"]["report"] = None
    chk = V.a5b_wrong_anchor([wrong])
    assert chk.status == V.FAIL and chk.details["failed"] == ["r_selftest:no_report"]


def test_a4_different_run_ids_pass_without_live_measure(fixture, tmp_path):
    run, _, _ = fixture
    after = _switched(run)
    after["id"] = "r_other"
    a, b = tmp_path / "a.json", tmp_path / "b.json"
    a.write_text(json.dumps(run), "utf-8")
    b.write_text(json.dumps(after), "utf-8")
    chk = V.a4_goal([str(a), str(b)])
    assert chk.status == V.PASS_NO_LIVE == "pass (live fetches not measured)"


def test_replay_note_and_unique_counts(fixture, tmp_path, capsys):
    run, cache_dir, run_file = fixture
    replay = copy.deepcopy(run)
    replay["id"] = "r_replay"
    for _p, d in V.walk(replay):
        if V.is_ref(d):
            d["mode"] = "cache"
    f2 = tmp_path / "replay.json"
    f2.write_text(json.dumps(replay), "utf-8")
    assert V.replay_notes([run, replay])[0].startswith("r_replay looks like a cache replay of r_selftest")
    assert V.replay_notes([run]) == []
    V.main(["--file", str(run_file), "--file", str(f2), "--cache-dir", str(cache_dir)])
    out = capsys.readouterr().out
    assert "2 eliminations (1 unique candidate)" in out and "unique by id and URL" in out
    assert "Note: r_replay looks like a cache replay" in out


def test_cache_dir_skips_run_snapshots(fixture, tmp_path):
    _run, cache_dir, run_file = fixture
    (cache_dir / "run.json").write_text(run_file.read_text("utf-8"), "utf-8")
    assert V.build_index([str(cache_dir)])[1] == 1


def test_selftest_index_is_the_cache_dir_index(fixture):
    _run, cache_dir, _ = fixture
    _r, cache = V.synthetic_fixture()
    assert V.index_from_data(cache) == V.build_index([str(cache_dir)])[0]
    assert not hasattr(V, "_index_from_items")


def test_load_errors_exit_2(tmp_path):
    assert V.main(["--file", str(tmp_path / "missing.json")]) == 2
    (tmp_path / "broken.json").write_text("{not json", "utf-8")
    assert V.main(["--file", str(tmp_path / "broken.json")]) == 2
    assert V.main(["--base", f"http://127.0.0.1:{_free_port()}", "--run", "r_x"]) == 2    # nothing listening


def test_json_must_stay_under_validation_dir(fixture, tmp_path, monkeypatch):
    _run, _cache_dir, run_file = fixture
    monkeypatch.setattr(V, "VALIDATION_DIR", tmp_path / "validation")
    with pytest.raises(SystemExit) as e:
        V.main(["--file", str(run_file), "--json", str(tmp_path / "elsewhere.json")])
    assert e.value.code == 2
    V.main(["--file", str(run_file), "--json"])
    assert (tmp_path / "validation" / "validate_run.json").exists()
