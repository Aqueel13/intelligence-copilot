"""Generator properties: deterministic, internally consistent, and planting what it claims."""

import pandas as pd
import pytest

from watchdog_backend.generator.insurance_claims import (
    CAUSES,
    GeneratorConfig,
    InsuranceClaimsGenerator,
)


def test_same_seed_same_data(pack) -> None:
    a = InsuranceClaimsGenerator(pack, GeneratorConfig(n_claims=200, seed=7)).generate()
    b = InsuranceClaimsGenerator(pack, GeneratorConfig(n_claims=200, seed=7)).generate()
    pd.testing.assert_frame_equal(a.events, b.events)
    pd.testing.assert_frame_equal(a.truth, b.truth)


def test_different_seed_different_data(pack) -> None:
    a = InsuranceClaimsGenerator(pack, GeneratorConfig(n_claims=200, seed=7)).generate()
    b = InsuranceClaimsGenerator(pack, GeneratorConfig(n_claims=200, seed=8)).generate()
    assert not a.cases["amount"].equals(b.cases["amount"])


def test_every_claim_starts_with_fnol_and_ends_closed(dataset) -> None:
    ev = dataset.events.sort_values(["case_id", "seq"])
    assert (ev.groupby("case_id")["activity"].first() == "FNOL").all()
    assert (ev.groupby("case_id")["activity"].last() == "Closed").all()


def test_events_are_chronological(dataset) -> None:
    ev = dataset.events.sort_values(["case_id", "seq"])
    assert (ev["ended_at"] >= ev["started_at"]).all()
    prev_end = ev.groupby("case_id")["ended_at"].shift()
    assert (ev["started_at"][prev_end.notna()] >= prev_end[prev_end.notna()]).all()


def test_senior_approval_exactly_above_threshold(dataset, pack) -> None:
    has_senior = dataset.events.query("activity == 'Senior Approval'")["case_id"].unique()
    above = dataset.cases.loc[
        dataset.cases["amount"] > pack.approval.senior_threshold_inr, "case_id"
    ]
    assert set(has_senior) == set(above)


def test_assessment_matches_line_of_business(dataset) -> None:
    lob = dataset.cases.set_index("case_id")["attributes"].map(lambda a: a["line_of_business"])
    survey = dataset.events.query("activity == 'Survey & Loss Assessment'")["case_id"]
    medical = dataset.events.query("activity == 'Medical Adjudication'")["case_id"]
    assert (lob[survey] == "motor").all()
    assert (lob[medical] == "health").all()
    assert survey.nunique() + medical.nunique() == len(dataset.cases)


def test_feedback_only_for_respondents_has_scores(dataset) -> None:
    fb = dataset.public_feedback()
    assert fb.loc[fb["responded_at"].isna(), ["csat", "nps", "comment"]].isna().all().all()
    assert fb.loc[fb["responded_at"].notna(), "csat"].between(1, 5).all()


def test_private_ground_truth_never_in_public_feedback(dataset) -> None:
    assert not [c for c in dataset.public_feedback().columns if c.startswith("_")]


# --- Calibration: the story the demo relies on. Ranges, not exact values. -------------


def test_calibration_breach_rates(dataset) -> None:
    s = dataset.summary()
    assert 0.25 <= s["sla_breach_rate"] <= 0.37
    assert s["breach_rate_without_any_planted_cause"] <= 0.15


def test_rc1_is_the_largest_cause(dataset) -> None:
    shares = {c: v["share_of_breaches"] for c, v in dataset.summary()["root_causes"].items()}
    assert shares["RC1"] >= 0.30
    assert shares["RC1"] == max(shares.values())
    for cause in CAUSES:
        assert shares[cause] >= 0.03, f"{cause} is too weak to be detectable"


def test_delegation_avoids_a_material_share_of_breaches(dataset) -> None:
    assert dataset.summary()["delegation_scenario"]["share_of_breaches_avoided"] >= 0.2


def test_dc1_health_equals_motor_within_band(dataset) -> None:
    for band, by_lob in dataset.summary()["decoys"]["DC1_mean_cycle_days_by_amount_band"].items():
        if band == "> ₹5L":  # too few motor claims for a tight comparison
            continue
        assert by_lob["health"] == pytest.approx(by_lob["motor"], abs=0.3), band


def test_dc3_respondents_understate_satisfaction(dataset) -> None:
    dc3 = dataset.summary()["decoys"]["DC3_csat"]
    assert dc3["respondent_mean_csat"] < dc3["true_mean_csat_all_customers"] - 0.2
