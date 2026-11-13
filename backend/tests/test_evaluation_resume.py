"""--resume bookkeeping: what counts as done, and which failures recover with time."""

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
