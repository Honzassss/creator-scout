"""Chat: subject mode (one named creator), the English scripted interview, the effective language
and the LLM budget hooks (docs/subject-mode.md section 8). No test calls a real API."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from anthropic.types import TextBlock, ToolUseBlock

from app.llm import budget, chat, client as llm_client
from app.models import Anchor, Brief, Candidate, CandidateRef, CriteriaSet, Run, SubjectSpec, make_source_ref

# --------------------------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------------------------


def _src(url: str):
    return make_source_ref(url=url, platform="instagram", mode="mock")


def subject_result(handle: str = "fit_peci_s_klarou", *, identity: str = "confirmed", status: str = "finished") -> dict:
    """A research_subject result in the shape of section 8.1 (what ApiChatContext returns)."""
    texts = {
        "confirmed": f"We are confident @{handle} is the creator you mean because the website fitpeceni.example is "
                     f"on the profile, TikTok @{handle} links back to this profile.",
        "likely": f"@{handle} is probably the creator you mean: the anchor city Brno is in the bio. "
                  "Their website or company ID would confirm it.",
        "not_found": f"We found no public profile @{handle} on Instagram, TikTok.",
    }
    return {
        "ok": True, "run_id": "r_subject", "status": status,
        "subject": {"raw": f"@{handle}", "platform": None if identity == "not_found" else "instagram", "handle": handle,
                    "candidate_id": None if identity == "not_found" else f"instagram:{handle}",
                    "status": "not_found" if identity == "not_found" else "resolved"},
        "anchor": {"city": None, "website": "fitpeceni.example", "company_id": None},
        "criteria_source": "preset:bakery",
        "identity": {"status": identity, "text": texts[identity]},
        "checks": {"pass": 9, "fail": 2, "unknown": 2, "items": [
            {"criterion_id": "topic_share", "label": "Topics", "status": "fail", "value": "0.3", "threshold": "0.4"},
            {"criterion_id": "discloses_ads", "label": "Ad disclosure", "status": "fail", "value": "2", "threshold": "0"},
            {"criterion_id": "cs_comment_share", "label": "Czech comments", "status": "unknown", "value": None, "threshold": "0.5"},
        ]},
        "key_findings": [
            {"id": "f:fit:topics", "kind": "fact", "text": "6 of 20 recent posts (30 %) are about food",
             "confidence": "medium", "why": "For your bakery: a creator who talks about food fits."},
            {"id": "i:undisclosed", "kind": "inference", "text": "2 brand posts carry no ad label",
             "confidence": "medium", "why": ""},
            {"id": "g:pricing", "kind": "gap", "text": "Pricing is never public", "confidence": "high", "why": ""},
            {"id": "f:extra", "kind": "fact", "text": "FOURTH FINDING", "confidence": "low", "why": ""},
        ],
        "less_relevant": 7,
        "claims": [{"claim": "exkluzivní ambasador @pekarna_a", "status": "conflicts_with_record", "confidence": "medium"}],
        "questions": ["How do you label paid posts?"],
        "outreach_draft_ready": True,
        "note": "Subject check: nothing is eliminated and there is no score.",
    }


def subject_run(criteria: CriteriaSet, handle: str = "fit_peci_s_klarou") -> Run:
    ref = CandidateRef(handle=handle, platform="instagram", found_via=["manual"], source=_src(f"https://instagram.com/{handle}"))
    cand = Candidate(id=f"instagram:{handle}", ref=ref, status="finalist")
    return Run(id="r_subject", criteria=criteria, candidates={cand.id: cand}, rounds=[], log=[], mode_summary={}, mode="subject",
               subject=SubjectSpec(raw=f"@{handle}", handle=handle, platform="instagram",
                                   anchor=Anchor(website="fitpeceni.example"), candidate_id=cand.id, status="resolved"))


class SubjectCtx:
    """FakeCtx (as in test_llm.py) plus research_subject and report_diffs on goal changes."""

    def __init__(self, lang: str = "en", result: dict | None = None) -> None:
        self.lang = lang
        self.history: list[dict] = []
        self.criteria: CriteriaSet | None = None
        self.run: Run | None = None
        self.calls: list[tuple] = []
        self.result = result

    def current_run(self):
        return self.run

    def current_criteria(self):
        return self.criteria

    async def propose_criteria(self, criteria):
        self.calls.append(("propose_criteria", criteria))
        self.criteria = criteria
        return {"ok": True}

    async def update_criterion(self, criterion_id, params=None, enabled=None):
        self.calls.append(("update_criterion", criterion_id, params, enabled))
        return {"ok": True, "report_diffs": [{"candidate_id": "instagram:fit_peci_s_klarou", "handle": "fit_peci_s_klarou",
                                              "summary": "The report is the same for this goal."}]} if self.run else {"ok": True}

    async def run_rounds(self, up_to):
        self.calls.append(("run_rounds", up_to))
        from tests.test_llm import make_run

        self.run = make_run(self.criteria)
        return {"ok": True}

    async def explain_elimination(self, candidate_id):
        self.calls.append(("explain_elimination", candidate_id))
        return {"ok": True}

    async def start_deep_vetting(self, candidate_ids):
        self.calls.append(("start_deep_vetting", candidate_ids))
        return {"ok": True}

    async def change_goal(self, brief):
        self.calls.append(("change_goal", brief))
        self.criteria = chat.criteria_for_brief(brief)
        out: dict = {"ok": True, "criteria_source": "preset:fitness"}
        if self.run is not None and self.run.mode == "subject":
            self.run.criteria = self.criteria
            out["report_diffs"] = [{
                "candidate_id": "instagram:fit_peci_s_klarou", "handle": "fit_peci_s_klarou",
                "summary": "Goal changed from bakery to fitness studio: 2 findings became key (ProteoMax is now a "
                           "competitor), 4 moved to less relevant, 3 new questions, outreach draft rewritten.",
                "added": 1, "removed": 0, "moved_up": 2, "moved_down": 4, "claims_changed": 0, "questions_added": 3,
                "outreach_changed": True,
                "key_findings": ["Collaboration with ProteoMax (labeled, 2026-09-20)", "12 of 20 posts are about fitness"],
            }]
        else:
            out["diff"] = {"dropped": [], "returned": []}
        return out

    async def draft_outreach(self, candidate_id):
        self.calls.append(("draft_outreach", candidate_id))
        return {"ok": True, "draft": {"cs": "Dobrý den", "en": "Hello"}}

    async def research_subject(self, subject, anchor=None, brief=None, preset=None):
        self.calls.append(("research_subject", subject, anchor, brief, preset))
        self.criteria = chat.criteria_for_brief(brief)
        result = self.result if self.result is not None else subject_result()
        if (result.get("subject") or {}).get("status") != "not_found":
            self.run = subject_run(self.criteria, (result.get("subject") or {}).get("handle") or "fit_peci_s_klarou")
        return result


class Events:
    def __init__(self) -> None:
        self.items: list[tuple[str, dict]] = []

    async def __call__(self, event: str, data: dict) -> None:
        self.items.append((event, data))

    def text(self) -> str:
        return "".join(d["text"] for e, d in self.items if e == "chat.delta")

    def clear(self) -> None:
        self.items.clear()


async def say(ctx, ev, msg: str) -> str:
    ev.clear()
    await chat.chat_turn(msg, ctx, ev)
    return ev.text()


def calls(ctx, name: str) -> list[tuple]:
    return [c for c in ctx.calls if c[0] == name]


# --------------------------------------------------------------------------------------------
# detection and extraction
# --------------------------------------------------------------------------------------------


def test_detection_vs_competitor_answer():
    tok = chat.is_subject_request("Check @fit_peci_s_klarou for my bakery in Brno", None, first=True)
    assert tok is not None and tok.handle == "fit_peci_s_klarou" and tok.raw == "@fit_peci_s_klarou"
    # the first message counts even without a verb; later ones need a check verb
    assert chat.is_subject_request("@brnenska_snidane", None, first=True) is not None
    assert chat.is_subject_request("@brnenska_snidane", None, first=False) is None
    assert chat.is_subject_request("prověř @brnenska_snidane", None, first=False) is not None
    assert chat.is_subject_request("podívej se na https://www.tiktok.com/@toman_ochutnava", "run", first=False).platform == "tiktok"
    # competitor answers contain handles too
    assert chat.is_subject_request("Check @pekarna_b, they are my competitor", "q5", first=False) is None
    assert chat.is_subject_request("Do 20 tisíc, konkurence @pekarna_b", "q4", first=False) is None
    # an e-mail address is not a handle; a post link is not a profile
    assert chat.subject_token("write to info@fitpeceni.example") is None
    assert chat.subject_token("check https://www.instagram.com/p/Cxyz123/") is None
    assert chat._post_link("check https://www.instagram.com/p/Cxyz123/")
    # profile links (any scheme / www / query) and a platform hint
    tok = chat.subject_token("look at instagram.com/kuba.jidlo.brno/?hl=cs")
    assert (tok.platform, tok.handle) == ("instagram", "kuba.jidlo.brno")
    tok = chat.subject_token("check @toman_ochutnava on TikTok")
    assert tok.platform == "tiktok" and tok.raw == "https://www.tiktok.com/@toman_ochutnava"


def test_detection_leaves_discovery_candidates_to_existing_flows():
    from tests.test_llm import make_run
    from app.presets import get_preset

    run = make_run(get_preset("bakery"))
    assert chat.is_subject_request("prověř @anna", None, first=False, run=run) is None
    assert chat.is_subject_request("prověř @someone_else", None, first=False, run=run) is not None


def test_anchor_extraction():
    ea = chat.extract_anchor
    # the business's city is not the creator's anchor
    assert ea("Check @fit_peci_s_klarou for my bakery in Brno") is None
    assert ea("Check @x, she is based in Brno") == {"city": "Brno"}
    assert ea("check @x from Bratislava for my café") == {"city": "Bratislava"}
    assert ea("prověř @x, je z Brna") == {"city": "Brno"}
    assert ea("her site is https://www.FitPeceni.example/kontakt") == {"website": "fitpeceni.example"}
    assert ea("IČO 1234567") == {"company_id": "01234567"}
    assert ea("company ID: CZ12345678") == {"company_id": "12345678"}
    assert ea("budget 100000 CZK") is None                       # bare digits only in an answer
    # answers to the anchor question
    assert ea("fitpeceni.example", answer=True) == {"website": "fitpeceni.example"}
    assert ea("Brno", answer=True) == {"city": "Brno"}
    assert ea("in Bratislava", answer=True) == {"city": "Bratislava"}
    assert ea("12345678", answer=True) == {"company_id": "12345678"}
    assert ea("777123456", answer=True) is None                  # a phone number is not an IČO
    for skip in ("skip", "Skip.", "nevím", "don't know", "přeskočit"):
        assert ea(skip, answer=True) == "skip", skip
    # social / e-mail hosts are never the creator's website
    assert ea("instagram.com/x", answer=True) is None
    assert ea("klara@gmail.com", answer=True) is None


def test_goal_extraction():
    eg = chat.extract_goal
    assert eg("Check @fit_peci_s_klarou for my bakery in Brno", "en") == {
        "preset": "bakery", "business": "bakery", "city": "Brno", "goal": ""}
    assert eg("my bakery in Brno, more people in the shop", "en", answer=True)["goal"] == "more people in the shop"
    g = eg("a flower shop in Olomouc, more orders for Valentine's day", "en", answer=True)
    assert g["preset"] is None and g["business"] == "flower shop" and g["city"] == "Olomouc"
    assert eg("prověř @x pro moji pekárnu v Brně", "cs")["business"] == "pekárna"
    # what the creator does is not the owner's business; nor is "for a friend"
    assert eg("Check @x, a fitness creator", "en") is None
    assert eg("check @x for a friend", "en") is None
    # the anchor city phrase does not become the business city
    assert eg("check @x based in Bratislava for my bakery", "en")["city"] is None


def test_validate_research_input():
    args, err = chat.validate_research_input(
        {"subject": " @Fit_Peci_S_Klarou ", "anchor": {"website": "https://www.fitpeceni.example/"},
         "brief": {"business_type": "bakery", "city": "Brno", "audience": "", "goal": "", "budget_hint": None,
                   "competitors": [], "lang": "cs"}}, "en")
    assert err is None and args["subject"] == "@Fit_Peci_S_Klarou"
    assert args["anchor"] == {"website": "fitpeceni.example"} and args["brief"].lang == "en"
    # preset alone gives the demo brief in the session language
    args, err = chat.validate_research_input({"subject": "@x", "preset": "bakery"}, "en")
    assert err is None and args["brief"].business_type == "bakery" and args["preset"] == "bakery"
    bad = [
        ({"brief": {"business_type": "bakery"}}, "subject"),
        ({"subject": "x" * 301, "brief": {"business_type": "bakery"}}, "subject"),
        ({"subject": "https://www.instagram.com/p/Cxyz/", "brief": {"business_type": "bakery"}}, "subject"),
        ({"subject": "@x"}, "brief"),
    ]
    for inp, missing in bad:
        args, err = chat.validate_research_input(inp, "en")
        assert args is None and err["ok"] is False and missing in err["missing"], inp
    for anchor in ({"city": "B" * 201}, {"city": 5}, {"phone": "123"}, "Brno"):
        args, err = chat.validate_research_input({"subject": "@x", "anchor": anchor, "preset": "bakery"}, "en")
        assert args is None and err["ok"] is False, anchor
    args, err = chat.validate_research_input({"subject": "@x", "preset": "pizza"}, "en")
    assert err is not None


async def test_live_tool_validates_before_calling_ctx():
    ctx, ev = SubjectCtx("en"), Events()
    state = chat._TurnState(message="check", lang="en")
    res, is_err = await chat._run_tool("research_subject", {"subject": "https://www.instagram.com/reel/abc/",
                                                            "brief": {"business_type": "bakery"}}, ctx, ev, state)
    assert is_err and "profile link" in res["error"] and not calls(ctx, "research_subject")
    res, is_err = await chat._run_tool("research_subject", {"subject": "@fit_peci_s_klarou", "preset": "bakery",
                                                            "brief": {"business_type": "bakery", "city": "Brno"}}, ctx, ev, state)
    assert not is_err and res["identity"]["status"] == "confirmed" and "anchor_note" in res
    (_, subject, anchor, brief, preset), = calls(ctx, "research_subject")
    assert subject == "@fit_peci_s_klarou" and anchor is None and brief.lang == "en" and preset == "bakery"

    class NoSubject(SubjectCtx):
        research_subject = None  # type: ignore[assignment]

    res, is_err = await chat._run_tool("research_subject", {"subject": "@x", "preset": "bakery"}, NoSubject(), ev, state)
    assert is_err and res["ok"] is False


# --------------------------------------------------------------------------------------------
# fallback subject flow
# --------------------------------------------------------------------------------------------


async def test_subject_flow_scenario_7():
    """Acceptance 7: one anchor question, the answer starts the run, a goal switch summarises the diff."""
    ctx, ev = SubjectCtx("en"), Events()
    text = await say(ctx, ev, "Check @fit_peci_s_klarou for my bakery in Brno")
    assert "To check the right @fit_peci_s_klarou and not a namesake or look-alike account" in text
    assert text.count("?") == 1 and not calls(ctx, "research_subject")
    assert ev.items[-1] == ("done", {"llm_mode": "fallback", "lang": "en"})

    text = await say(ctx, ev, "fitpeceni.example")
    (_, subject, anchor, brief, preset), = calls(ctx, "research_subject")
    assert subject == "@fit_peci_s_klarou" and anchor == {"website": "fitpeceni.example"}
    assert preset == "bakery" and brief.business_type == "bakery" and brief.city == "Brno" and brief.lang == "en"
    assert text.startswith("We are confident @fit_peci_s_klarou is the creator you mean because")
    assert "[fact, medium confidence] 6 of 20 recent posts" in text and "[gap, high confidence]" in text
    assert "FOURTH FINDING" not in text                                      # at most 3 key findings
    assert "2 did not pass (Topics, Ad disclosure)" in text and "2 could not be checked" in text
    assert "“exkluzivní ambasador @pekarna_a” conflicts with the record" in text
    assert "Nothing was eliminated and there is no score: these are checks with sources." in text
    assert "Try “what about my fitness studio?”" in text
    assert any(e == "chat.tool" and d["name"] == "research_subject" for e, d in ev.items)
    for word in ("score:", "best", "trustworthy"):
        assert word not in text.replace("there is no score", "")

    text = await say(ctx, ev, "what about my fitness studio?")
    (_, goal), = calls(ctx, "change_goal")
    assert goal.business_type == "fitness studio" and goal.city == "Brno" and goal.lang == "en"
    assert "re-ordered and rewrote the report for @fit_peci_s_klarou" in text
    assert "ProteoMax is now a competitor" in text and "• Collaboration with ProteoMax" in text
    assert not calls(ctx, "run_rounds")


async def test_one_question_per_missing_item_then_run():
    ctx, ev = SubjectCtx("en"), Events()
    text = await say(ctx, ev, "Check @fit_peci_s_klarou")
    assert "where is the creator based (city), or what is their website or company ID (IČO)?" in text
    assert "What is your business" not in text
    text = await say(ctx, ev, "She is based in Brno")
    assert "What is your business and what should the creator help with?" in text and "where is the creator" not in text
    assert not calls(ctx, "research_subject")
    await say(ctx, ev, "a flower shop in Olomouc, more orders for Valentine's day")
    (_, subject, anchor, brief, preset), = calls(ctx, "research_subject")
    assert anchor == {"city": "Brno"} and preset is None
    assert brief.business_type == "flower shop" and brief.city == "Olomouc" and brief.goal.startswith("more orders")


async def test_everything_in_one_message_runs_at_once():
    ctx, ev = SubjectCtx("en"), Events()
    await say(ctx, ev, "Check https://www.instagram.com/kuba.jidlo.brno/ (based in Brno) for my bakery in Brno")
    (_, subject, anchor, brief, preset), = calls(ctx, "research_subject")
    assert subject == "https://www.instagram.com/kuba.jidlo.brno/" and anchor == {"city": "Brno"} and preset == "bakery"


async def test_skip_anchor():
    result = subject_result(identity="likely")
    ctx, ev = SubjectCtx("en", result), Events()
    await say(ctx, ev, "Check @fit_peci_s_klarou for my bakery in Brno")
    text = await say(ctx, ev, "skip")
    (_, _subject, anchor, _brief, _preset), = calls(ctx, "research_subject")
    assert anchor is None
    assert "is probably the creator you mean" in text and "at most “likely”" in text


async def test_unreadable_anchor_answer_goes_on_without_one():
    ctx, ev = SubjectCtx("en"), Events()
    await say(ctx, ev, "Check @fit_peci_s_klarou for my bakery in Brno")
    await say(ctx, ev, "hmm, I really have no clue about that")
    (_, _subject, anchor, _brief, _preset), = calls(ctx, "research_subject")
    assert anchor is None


async def test_subject_not_found_and_running():
    ctx, ev = SubjectCtx("en", subject_result("nobody_here_xyz", identity="not_found")), Events()
    text = await say(ctx, ev, "Check @nobody_here_xyz, she is based in Brno, for my bakery in Brno")
    assert "We found no public profile @nobody_here_xyz" in text and "profile link" in text
    assert "Try “what about" not in text and ctx.run is None
    ctx, ev = SubjectCtx("en", subject_result(status="running")), Events()
    text = await say(ctx, ev, "Check @fit_peci_s_klarou, she is based in Brno, for my bakery in Brno")
    assert "I am checking @fit_peci_s_klarou now" in text


async def test_subject_flow_czech():
    ctx, ev = SubjectCtx("cs"), Events()
    text = await say(ctx, ev, "Prověř @fit_peci_s_klarou pro moji pekárnu v Brně")
    assert "Abych prověřil správný účet @fit_peci_s_klarou" in text and "IČO?" in text
    await say(ctx, ev, "je z Brna")
    (_, _s, anchor, brief, preset), = calls(ctx, "research_subject")
    assert anchor == {"city": "Brno"} and brief.business_type == "pekárna" and brief.lang == "cs" and preset == "bakery"
    text = await say(ctx, ev, "a co pro moje fitness studio?")
    (_, goal), = calls(ctx, "change_goal")
    assert goal.business_type == "fitness studio" and "Report pro @fit_peci_s_klarou jsem přeřadil" in text


async def test_competitor_answer_with_handle_is_not_a_subject_request():
    ctx, ev = SubjectCtx("cs"), Events()
    for msg in ("Mám pekárnu v Brně", "Rodiny a mladí lidé", "Víc lidí v prodejně", "Do 20 tisíc"):
        await say(ctx, ev, msg)
    assert "A konkurenti" in ev.text()                       # q5 pending
    await say(ctx, ev, "prověř @pekarna_b, to je konkurence")
    assert not calls(ctx, "research_subject")
    assert ctx.criteria is not None and any("pekarna_b" in c["handles"] for c in ctx.criteria.brief.competitors)


async def test_refusal_and_scope_detours_keep_the_anchor_question():
    ctx, ev = SubjectCtx("en"), Events()
    await say(ctx, ev, "Check @fit_peci_s_klarou for my bakery in Brno")
    text = await say(ctx, ev, "what do you check?")
    assert "where is the creator based" in text
    text = await say(ctx, ev, "fitpeceni.example")
    assert calls(ctx, "research_subject") and calls(ctx, "research_subject")[0][2] == {"website": "fitpeceni.example"}


async def test_subject_run_routing():
    ctx, ev = SubjectCtx("en"), Events()
    await say(ctx, ev, "Check @fit_peci_s_klarou, based in Brno, for my bakery in Brno")
    assert ctx.run is not None and ctx.run.mode == "subject"
    text = await say(ctx, ev, "run it")
    assert not calls(ctx, "run_rounds") and "This check is about one creator (@fit_peci_s_klarou)" in text
    text = await say(ctx, ev, "why did @fit_peci_s_klarou drop out?")
    assert "Nobody drops out in a single-creator check" in text
    text = await say(ctx, ev, "turn off format")
    assert calls(ctx, "update_criterion") and "The report is the same for this goal." in text
    await say(ctx, ev, "outreach draft please")
    assert calls(ctx, "draft_outreach") == [("draft_outreach", "instagram:fit_peci_s_klarou")]
    # another creator -> another research_subject
    await say(ctx, ev, "now check @brnenska_snidane, she is based in Brno")
    assert [c[1] for c in calls(ctx, "research_subject")] == ["@fit_peci_s_klarou", "@brnenska_snidane"]
    assert calls(ctx, "research_subject")[1][3].business_type == "bakery"   # goal reused from the session


def test_goal_switch_phrases():
    rx = chat._RX_GOAL_SWITCH
    from app.llm.text import fold

    for s in ("what about my fitness studio?", "How about our café?", "for my gym instead",
              "a co pro moje fitness studio?", "A co moje kavárna?", "místo toho fitness studio"):
        assert rx.search(fold(s)), s
    assert not rx.search(fold("what do you check?"))


# --------------------------------------------------------------------------------------------
# English interview and the effective language
# --------------------------------------------------------------------------------------------


async def test_english_interview_end_to_end_bakery():
    ctx, ev = SubjectCtx("en"), Events()
    transcript = [await say(ctx, ev, "Hello")]
    assert "What do you sell, and where?" in transcript[-1]
    transcript.append(await say(ctx, ev, "I have a bakery in Brno"))
    assert "Got it: bakery in Brno." in transcript[-1] and "Who do you want to sell to?" in transcript[-1]
    transcript.append(await say(ctx, ev, "Families and young people"))
    assert "What should the campaign achieve?" in transcript[-1]
    transcript.append(await say(ctx, ev, "More people in the shop and a new sourdough bread"))
    assert "Roughly how much can you spend" in transcript[-1]
    transcript.append(await say(ctx, ev, "Up to 20k CZK. Competitors: Bakery B @pekarna_b"))
    cs = ctx.criteria
    assert cs is not None and cs.brief.business_type == "bakery" and cs.brief.city == "Brno" and cs.brief.lang == "en"
    assert cs.brief.competitors == [{"name": "Bakery B", "handles": ["pekarna_b"]}]
    assert cs.brief.budget_hint == "Up to 20k CZK"
    assert "Shall I start the search" in transcript[-1]
    transcript.append(await say(ctx, ev, "yes"))
    assert ("run_rounds", 3) in ctx.calls and "Vet 2 finalists in depth?" in transcript[-1]
    transcript.append(await say(ctx, ev, "yes please"))
    assert calls(ctx, "start_deep_vetting") and "Nothing is sent" in transcript[-1]
    transcript.append(await say(ctx, ev, "why did @travel_tom drop out?"))
    assert "dropped out in round 2" in transcript[-1]
    transcript.append(await say(ctx, ev, "outreach for @anna"))
    assert "NOT SENT" in transcript[-1]
    transcript.append(await say(ctx, ev, "max 30,000 followers"))
    assert calls(ctx, "update_criterion")[-1][2] == {"min": 1000, "max": 30000}  # preset min is 1,000 since engine-fixes
    transcript.append(await say(ctx, ev, "change goal to a fitness studio in Brno"))
    assert calls(ctx, "change_goal")[-1][1].business_type == "fitness studio"
    transcript.append(await say(ctx, ev, "who is the best?"))
    assert "best" in transcript[-1] and "you decide" in transcript[-1]
    full = "\n".join(transcript)
    for czech in ("pekárna", "Prověřit", "Díky", "Rozumím", "kole", "Zpátky"):
        assert czech not in full, czech
    assert all(d.get("lang") == "en" for e, d in ev.items if e == "done")


async def test_english_generic_brief_parses_budget_with_separators():
    ctx, ev = SubjectCtx("en"), Events()
    for msg in ("We run a flower shop in Olomouc", "Couples and offices", "More orders for Valentine's day",
                "CZK 20,000, no competitors"):
        await say(ctx, ev, msg)
    cs = ctx.criteria
    assert cs.brief.budget_hint == "CZK 20,000" and cs.brief.competitors == []
    assert next(c for c in cs.criteria if c.kind == "followers_range").params == {"min": 5000, "max": 50000}


async def test_english_demo_shortcut_never_shows_czech_business():
    ctx, ev = SubjectCtx("en"), Events()
    text = await say(ctx, ev, "demo")
    assert "Demo brief: bakery, Brno" in text and "pekárna" not in text
    assert ctx.criteria.brief.lang == "en" and ctx.criteria.brief.business_type == "bakery"


def test_effective_language():
    assert chat.effective_lang([], "Check @fit_peci_s_klarou for my bakery in Brno", "cs") == "en"
    assert chat.effective_lang([], "Mám pekárnu v Brně", "en") == "cs"
    assert chat.effective_lang([], "Dobrý den", "en") == "cs"
    assert chat.effective_lang([], "Hi", "cs") == "cs"            # too short: the UI language
    assert chat.effective_lang([], "demo", "en") == "en"
    # sticky: the first owner message decides
    hist = [{"role": "user", "content": "I run a bakery in Brno"}, {"role": "assistant", "content": "Got it."}]
    assert chat.effective_lang(hist, "Rodiny a mladí lidé v Brně", "cs") == "en"
    # JSON in an operator message does not tip the detection
    assert chat.detect_owner_lang('Cíl se mění. Nové zadání: {"business_type": "bakery", "audience": "families"}. '
                                  "Navrhni kritéria pro tento cíl nástrojem propose_criteria.") == "cs"


async def test_effective_language_sets_ctx_lang_and_done():
    ctx, ev = SubjectCtx("cs"), Events()
    text = await say(ctx, ev, "Check @fit_peci_s_klarou for my bakery in Brno")
    assert ctx.lang == "en" and "To check the right" in text
    assert ev.items[-1] == ("done", {"llm_mode": "fallback", "lang": "en"})
    ctx, ev = SubjectCtx("en"), Events()
    text = await say(ctx, ev, "Dobrý den, mám pekárnu v Brně")
    assert ctx.lang == "cs" and "Komu chcete prodávat?" in text


def test_board_state_names_subject_mode():
    from app.presets import get_preset

    ctx = SubjectCtx("en")
    ctx.criteria = get_preset("bakery")
    ctx.run = subject_run(ctx.criteria)
    note = chat._board_state(ctx)
    assert "mode=subject" in note and "@fit_peci_s_klarou" in note and "Never call run_rounds" in note
    assert "reply in English" in note


def test_chat_system_prompt_covers_subject_mode():
    from app.llm import prompts

    p = prompts.CHAT_SYSTEM
    assert "research_subject" in p and "report_diffs" in p and "ONE question per turn" in p
    assert "Reply in the owner's language" in p


# --------------------------------------------------------------------------------------------
# LLM budget hooks
# --------------------------------------------------------------------------------------------


class _FakeStream:
    def __init__(self, texts, final):
        self.texts, self.final = texts, final

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    def __aiter__(self):
        async def gen():
            for t in self.texts:
                yield SimpleNamespace(type="text", text=t)
        return gen()

    async def get_final_message(self):
        return self.final


class _FakeClient:
    def __init__(self, script):
        self.script = list(script)
        self.calls: list[dict] = []
        self.messages = self

    def stream(self, **kw):
        self.calls.append(kw)
        return self.script.pop(0)


async def test_budget_exhausted_before_output_falls_back(monkeypatch):
    fake = _FakeClient([])
    monkeypatch.setattr(llm_client, "get_client", lambda: fake)

    async def no_budget(task):
        assert task == "chat"
        return False

    monkeypatch.setattr(budget, "spend", no_budget)
    ctx, ev = SubjectCtx("en"), Events()
    text = await say(ctx, ev, "Check @fit_peci_s_klarou for my bakery in Brno")
    assert not fake.calls                                   # no request left the process
    assert "To check the right @fit_peci_s_klarou" in text
    assert ev.items[-1] == ("done", {"llm_mode": "fallback", "lang": "en"})
    assert [m["role"] for m in ctx.history] == ["user", "assistant"]


async def test_budget_exhausted_after_a_tool_renders_the_result(monkeypatch):
    final = SimpleNamespace(stop_reason="tool_use", content=[
        ToolUseBlock(type="tool_use", id="tu1", name="research_subject",
                     input={"subject": "@fit_peci_s_klarou", "preset": "bakery", "anchor": {"website": "fitpeceni.example"},
                            "brief": {"business_type": "bakery", "city": "Brno", "audience": "", "goal": "",
                                      "budget_hint": None, "competitors": [], "lang": "en"}})])
    fake = _FakeClient([_FakeStream([], final)])
    monkeypatch.setattr(llm_client, "get_client", lambda: fake)
    left = {"n": 1}

    async def one_request(task):
        left["n"] -= 1
        return left["n"] >= 0

    monkeypatch.setattr(budget, "spend", one_request)
    ctx, ev = SubjectCtx("en"), Events()
    text = await say(ctx, ev, "Check @fit_peci_s_klarou (fitpeceni.example) for my bakery in Brno")
    assert calls(ctx, "research_subject") and len(fake.calls) == 1
    # the tool already ran: its result is shown with the deterministic formatter, not "try again"
    assert "Sorry, the reply did not finish" not in text
    assert "@fit_peci_s_klarou" in text and "Nothing was eliminated" in text
    assert ev.items[-1] == ("done", {"llm_mode": "fallback", "lang": "en"})
    # the history stays valid for the next request: no dangling tool_use
    assert ctx.history[-1]["role"] == "assistant"


async def test_openrouter_chat_task_disabled_uses_fallback(monkeypatch):
    monkeypatch.setattr(llm_client, "get_client", lambda: None)
    monkeypatch.setattr(llm_client, "openrouter_active", lambda: True)
    monkeypatch.setattr(budget, "llm_task_enabled", lambda task: False)

    async def boom(*a, **kw):  # pragma: no cover - must not be reached
        raise AssertionError("stream_chat must not run when the chat task is disabled")

    from app.llm import openrouter

    monkeypatch.setattr(openrouter, "stream_chat", boom)
    ctx, ev = SubjectCtx("en"), Events()
    await say(ctx, ev, "Hello")
    assert ev.items[-1][1]["llm_mode"] == "fallback"


async def test_anthropic_stream_spends_one_request_per_call(monkeypatch):
    fake = _FakeClient([_FakeStream(["Hi!"], SimpleNamespace(stop_reason="end_turn",
                                                              content=[TextBlock(type="text", text="Hi!")]))])
    monkeypatch.setattr(llm_client, "get_client", lambda: fake)
    spent: list[str] = []

    async def count(task):
        spent.append(task)
        return True

    monkeypatch.setattr(budget, "spend", count)
    ctx, ev = SubjectCtx("en"), Events()
    await say(ctx, ev, "Hello there, how does this work?")
    assert spent == ["chat"] and ev.items[-1] == ("done", {"llm_mode": "llm", "lang": "en"})


# --------------------------------------------------------------------------------------------
# end to end through the API (fallback chat -> subject run)
# --------------------------------------------------------------------------------------------


async def test_api_fallback_chat_starts_subject_run():
    import httpx

    from app import main

    from tests.test_api import parse_sse

    await main.reset_runtime_state()
    transport = httpx.ASGITransport(app=main.app)
    try:
        async with httpx.AsyncClient(transport=transport, base_url="http://test", timeout=120) as client:
            r = await client.post("/api/chat", json={"message": "Check @fit_peci_s_klarou for my bakery in Brno", "lang": "en"})
            evs = parse_sse(r.text)
            assert evs[-1][1] == "done" and not [d for _, e, d in evs if e == "error"]
            chat_id = evs[-1][2]["chat_id"]
            text = "".join(d["text"] for _, e, d in evs if e == "chat.delta")
            assert "To check the right @fit_peci_s_klarou" in text
            r = await client.post("/api/chat", json={"message": "fitpeceni.example", "lang": "en", "chat_id": chat_id})
            evs = parse_sse(r.text)
            assert not [d for _, e, d in evs if e == "error"], evs
            tool = next(d for _, e, d in evs if e == "chat.tool" and d["name"] == "research_subject")
            assert tool["input"]["anchor"] == {"website": "fitpeceni.example"}
            run_id = evs[-1][2]["run_id"] or tool["result"].get("run_id")
            assert run_id
            await main.wait_idle(run_id)
            run = (await client.get(f"/api/runs/{run_id}")).json()
            assert run["mode"] == "subject" and run["subject"]["handle"] == "fit_peci_s_klarou"
            text = "".join(d["text"] for _, e, d in evs if e == "chat.delta")
            assert "Nothing was eliminated and there is no score" in text or "I am checking" in text
    finally:
        await main.reset_runtime_state()


async def test_business_answer_to_the_anchor_question_is_not_the_anchor():
    ctx, ev = SubjectCtx("en"), Events()
    await say(ctx, ev, "Check @fit_peci_s_klarou")
    text = await say(ctx, ev, "I run a bakery in Brno")
    assert "where is the creator based" in text and not calls(ctx, "research_subject")   # asked once more
    await say(ctx, ev, "no idea")
    (_, _s, anchor, brief, preset), = calls(ctx, "research_subject")
    assert anchor is None and preset == "bakery" and brief.city == "Brno"


async def test_check_verb_on_a_discovery_candidate_explains_instead():
    ctx, ev = SubjectCtx("en"), Events()
    for msg in ("demo", "yes"):
        await say(ctx, ev, msg)
    assert ctx.run is not None and ctx.run.mode == "discovery"
    text = await say(ctx, ev, "check @travel_tom")
    assert not calls(ctx, "research_subject") and ("explain_elimination", "instagram:travel_tom") in ctx.calls
    assert "dropped out in round 2" in text


# --------------------------------------------------------------------------------------------
# Review fixes: language with Czech names, discovery openers with a handle, name-only subjects,
# anchor detours, goal change keeps the owner's own business
# --------------------------------------------------------------------------------------------


@pytest.mark.parametrize("msg", [
    "Check Jakub Horák from Brno for my bakery",
    "I want to check the creator Ondřej Toman for my fitness studio in Brno",
    "Please check Pekárna Kubík in Brno for my café",
    "Check Klára Veselá, IČO 12345678, for my fitness studio",
])
def test_czech_names_do_not_flip_an_english_session(msg):
    assert chat.effective_lang([], msg, "en") == "en"


def test_greeting_does_not_decide_the_language():
    hist = [{"role": "user", "content": "Hi"}, {"role": "assistant", "content": "Dobrý den!"}]
    assert chat.effective_lang(hist, "I run a bakery in Brno and want more customers", "cs") == "en"
    hist = [{"role": "user", "content": "Ahoj"}, {"role": "assistant", "content": "Hello!"}]
    assert chat.effective_lang(hist, "Mám pekárnu v Brně a chci víc zákazníků", "en") == "cs"


@pytest.mark.parametrize("msg,lang", [
    ("I run a bakery in Brno and want more customers; our main competitor is @pekarna_b", "en"),
    ("Mám pekárnu v Brně, hlavní konkurence je @pekarna_b, hledám tvůrce", "cs"),
    ("Find creators like @kuba.jidlo.brno for my bakery in Brno", "en"),
])
async def test_discovery_opener_naming_a_handle_is_not_a_subject_check(msg, lang):
    ctx, ev = SubjectCtx(lang), Events()
    text = await say(ctx, ev, msg)
    assert not calls(ctx, "research_subject")
    assert "To check the right" not in text and "Abych prověřil správný" not in text
    assert ("Who do you want to sell to?" in text) if lang == "en" else ("Komu chcete prodávat?" in text)


async def test_name_only_subject_asks_for_the_account_then_checks_it():
    ctx, ev = SubjectCtx("en"), Events()
    text = await say(ctx, ev, "Check Jakub Horák from Brno for my bakery")
    assert "Instagram or TikTok account" in text and "namesake" in text
    assert "Who do you want to sell to?" not in text and not calls(ctx, "research_subject")
    await say(ctx, ev, "@kuba.jidlo.brno")
    (_, subject, anchor, brief, _preset), = calls(ctx, "research_subject")
    assert subject == "@kuba.jidlo.brno" and anchor == {"city": "Brno"} and brief.business_type == "bakery"


async def test_anchor_detours_do_not_start_a_check():
    ctx, ev = SubjectCtx("en"), Events()
    await say(ctx, ev, "Check @toman_ochutnava for my fitness studio")
    text = await say(ctx, ev, "email him our offer please")
    assert "never send" in text and "Back to the question" in text and not calls(ctx, "research_subject")
    text = await say(ctx, ev, "what is IČO?")
    assert "company ID" in text and not calls(ctx, "research_subject")
    await say(ctx, ev, "Brno")
    (_, _s, anchor, _b, _p), = calls(ctx, "research_subject")
    assert anchor == {"city": "Brno"}


async def test_goal_switch_keeps_the_owners_business_and_competitors():
    ctx, ev = SubjectCtx("en"), Events()
    await say(ctx, ev, "Check @fit_peci_s_klarou (fitpeceni.example) for my bakery in Brno")
    await say(ctx, ev, "What about my yoga studio? Our competitor is @jogacentrum_brno")
    brief = calls(ctx, "change_goal")[-1][1]
    assert brief.business_type == "yoga studio"
    assert [c["handles"] for c in brief.competitors] == [["jogacentrum_brno"]]
    await say(ctx, ev, "what about a flower shop in Brno?")
    brief = calls(ctx, "change_goal")[-1][1]
    assert brief.business_type == "flower shop" and brief.goal == "" and brief.audience == ""
    assert brief.budget_hint is None and "sourdough" not in brief.model_dump_json()
    await say(ctx, ev, "what about my fitness studio?")
    brief = calls(ctx, "change_goal")[-1][1]
    assert brief.business_type == "fitness studio" and {c["name"] for c in brief.competitors} == {"FitZone Brno", "ProteoMax"}


async def test_goal_switch_after_not_found_says_there_is_nothing_to_rewrite():
    ctx, ev = SubjectCtx("en", result=subject_result("does_not_exist_xyz", identity="not_found")), Events()
    await say(ctx, ev, "Check @does_not_exist_xyz for my bakery in Brno")
    await say(ctx, ev, "Brno")
    ctx.run = subject_run(ctx.criteria, "does_not_exist_xyz")
    ctx.run.candidates = {}
    ctx.run.subject.status = "not_found"
    text = await say(ctx, ev, "what about my fitness studio?")
    assert "no report to rewrite" in text and "as soon as the check finishes" not in text


def test_name_requests_are_detected_only_without_a_handle():
    assert chat.subject_name("Check Jakub Horák from Brno for my bakery") == "Jakub Horák"
    assert chat.subject_name("Research the bakery Pekarna Kubik in Brno, ICO 12345678, for my coffee roastery") == "Pekarna Kubik"
    assert chat.subject_name("Prověř Pekárnu Kubík v Brně") == "Pekárnu Kubík"
    assert chat.subject_name("Check @kuba.jidlo.brno for my bakery") is None
    assert chat.subject_name("I run a bakery in Brno") is None
