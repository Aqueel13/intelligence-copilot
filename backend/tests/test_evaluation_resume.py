"""--resume bookkeeping: what counts as done, and which failures recover with time."""

import json

from watchdog_backend.evaluation.__main__ import _is_daily_quota, _resume_key

TPD = (
    "RateLimitError: Error code: 429 - {'error': {'message': 'Rate limit reached for model "
    "`openai/gpt-oss-20b` in organization `org_<redacted>` service tier `on_demand` on tokens "
    "per day (TPD): Limit 200000, Used 199524, Requested 4998."
)
OTPM = (
    "RateLimitError: Error code: 429 - {'error': {'message': \"Request too large for model "
    "`qwen/qwen3.8-27b` in organization `org_<redacted>` service tier `on_demand` on output "
    "tokens per minute (OTPM): Limit 1000, Requested 2234."
)


def test_daily_quota_recovers_but_request_too_large_does_not():
    assert _is_daily_quota(TPD)
    assert not _is_daily_quota(OTPM)
    assert not _is_daily_quota("NotFoundError: Error code: 404")


def test_resume_key_ignores_run_details():
    a = {"suite": "investigation", "model": "m", "seed": 7, "question_id": "q", "ok": False}
    b = {**a, "ok": True, "duration_s": 12}
    assert _resume_key(a) == _resume_key(b)
    assert _resume_key({"suite": "qa", "model": "m", "question": "x"}) == ("qa", "m", "x")


def test_report_does_not_list_resumed_quota_refusals_as_fixes(tmp_path):
    from watchdog_backend.evaluation.report import _load

    base = {"suite": "investigation", "domain": "insurance_claims", "model": "m", "seed": 7}
    rows = [
        {**base, "question_id": "a", "ok": False, "error": TPD},  # resumed later
        {**base, "question_id": "b", "ok": False, "error": OTPM},  # a real failure, re-run
        {**base, "question_id": "a", "ok": True},
        {**base, "question_id": "b", "ok": True},
    ]
    (tmp_path / "meta.json").write_text('{"started": "x", "domain": "insurance_claims"}')
    (tmp_path / "results.jsonl").write_text("\n".join(json.dumps(r) for r in rows))
    records, _, superseded = _load([tmp_path])
    assert len(records) == 2 and all(r["ok"] for r in records)
    assert [r["question_id"] for r in superseded] == ["b"]
