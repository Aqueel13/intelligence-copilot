"""Synthetic Insurance Claims generator with planted root causes and decoys.

Design:
- Each claim gets ALL of its random draws up front (`Draws`). The same claim can then be
  re-simulated with one planted cause switched off, using identical randomness. The
  difference is an exact counterfactual: "this claim breached *because of* RC1".
- Durations follow a working calendar (Mon–Fri 09:00–18:00 IST), so nights and weekends
  show up as waiting time exactly as they would in a real event log.
- The output includes per-claim ground truth and a summary. Neither is ever loaded into the
  database the copilot can see; they exist for tests and evaluation only.

Planted causes (see docs/PROJECT_BRIEF.md §5):
  RC1  Senior approval queue understaffed for claims > ₹2L (and getting worse over time)
  RC2  Broker-channel claims often arrive with missing documents
  RC3  Team B's verification work is rejected by QA far more often
  RC4  Handoffs late on Friday wait for the Monday backlog
Decoys:
  DC1  Health looks slower, but only because health claims are higher-value (→ RC1)
  DC2  Pune looks worse, but it is tiny and broker-heavy (→ RC2)
  DC3  Respondent CSAT understates true CSAT (non-response bias)
"""

import math
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from watchdog_backend.domain.pack import DomainPack
from watchdog_backend.generator import comments
from watchdog_backend.generator.calendar import WorkCalendar
from watchdog_backend.generator.common import (
    GeneratedDataset,
    SimEvent,
    SimResult,
    choose,
    hours,
    lognormal,
)

CAUSES = ("RC1", "RC2", "RC3", "RC4")

# How each catalogue action changes the world, in generator terms (the next-month simulator).
ACTION_EFFECTS: dict[str, dict[str, object]] = {
    "delegate_mid_value_approvals": {"rc1_exempt_max_amount": 500_000},
    "add_senior_adjuster_capacity": {"rc1_enabled": False},
    "enforce_broker_checklist": {"doc_request_broker_total": 0.06},  # = the base rate
    "retrain_team_b": {"qa_reject_team_b_total": 0.05},  # = the base rate
    "saturday_rota": {"rc4_probability": 0.0},
}
NO_CAUSES: frozenset[str] = frozenset()
ALL_CAUSES: frozenset[str] = frozenset(CAUSES)
MAX_DOC_REQUESTS = 2
MAX_QA_ROUNDS = 3
RC4_SLOTS = 16


@dataclass(frozen=True)
class GeneratorConfig:
    n_claims: int = 5000
    seed: int = 42
    # Trend window: RC1 worsens from `start` to `end` (and keeps worsening after it).
    start: date = date(2026, 4, 1)
    end: date = date(2026, 9, 30)
    # Generation window: FNOL dates are drawn from here (defaults to the trend window).
    # The simulator uses it to append later months that continue the same trends.
    window_start: date | None = None
    window_end: date | None = None
    id_offset: int = 0  # case numbers start after this (for appended months)

    lob_weights: dict[str, float] = field(default_factory=lambda: {"motor": 0.55, "health": 0.45})
    channel_weights: dict[str, float] = field(
        default_factory=lambda: {"direct": 0.45, "broker": 0.30, "agent": 0.25}
    )
    # DC2: Pune is small and broker-heavy.
    pune_channel_weights: dict[str, float] = field(
        default_factory=lambda: {"direct": 0.25, "broker": 0.60, "agent": 0.15}
    )
    region_weights: dict[str, float] = field(
        default_factory=lambda: {
            "Mumbai": 0.24,
            "Delhi NCR": 0.22,
            "Bengaluru": 0.18,
            "Chennai": 0.13,
            "Hyderabad": 0.12,
            "Kolkata": 0.095,
            "Pune": 0.015,
        }
    )
    teams: tuple[str, ...] = ("Team A", "Team B", "Team C")

    # Amounts (lognormal). DC1: health skews higher-value.
    motor_amount_median: float = 60_000
    motor_amount_sigma: float = 0.95
    health_amount_median: float = 170_000
    health_amount_sigma: float = 0.80
    amount_floor: float = 5_000
    amount_cap: float = 2_500_000

    # RC2: missing documents
    doc_request_base: float = 0.06  # every channel
    doc_request_broker_total: float = 0.24  # broker total, including the base
    doc_request_repeat_factor: float = 0.35  # chance multiplier for a second request

    # RC3: QA rejection
    qa_reject_base: float = 0.05
    qa_reject_team_b_total: float = 0.18
    qa_reject_repeat_factor: float = 0.40
    rework_requeue_wait_median_h: float = 9.0

    # RC1: senior approval queue (extra waiting in working hours, rising Apr → Sep)
    rc1_enabled: bool = True
    # Claims up to this amount skip the senior queue (delegated to Team Leads); None = no one
    rc1_exempt_max_amount: float | None = None
    senior_base_wait_median_h: float = 4.0
    rc1_extra_median_first_month_h: float = 12.0
    rc1_extra_median_last_month_h: float = 26.0

    # RC4: late-Friday handoffs
    rc4_from: time = time(15, 0)
    rc4_probability: float = 0.8
    rc4_backlog_hours: tuple[float, float] = (3.0, 8.0)

    # Feedback (DC3: unhappy customers respond more)
    response_rate_at_csat5: float = 0.16
    response_rate_step: float = 0.08  # extra response probability per point below 5
    comment_probability: float = 0.65


class Draws:
    """Every random number one claim can ever need, drawn in a fixed order."""

    def __init__(self, rng: np.random.Generator) -> None:
        u, z = rng.random, rng.standard_normal
        self.fnol_mode, self.fnol_day, self.fnol_hour, self.fnol_work = u(4)
        self.lob, self.region, self.channel, self.team, self.senior_who = u(5)
        self.amount = z()
        self.dc_wait, self.dc_work = z(MAX_DOC_REQUESTS + 1), z(MAX_DOC_REQUESTS + 1)
        self.req_base, self.req_extra = u(MAX_DOC_REQUESTS), u(MAX_DOC_REQUESTS)
        self.req_duration = z(MAX_DOC_REQUESTS)
        self.assess_wait, self.assess_work = z(2)
        self.ver_wait, self.ver_work = z(MAX_QA_ROUNDS), z(MAX_QA_ROUNDS)
        self.qa_wait, self.qa_work = z(MAX_QA_ROUNDS), z(MAX_QA_ROUNDS)
        self.qa_base, self.qa_extra = u(MAX_QA_ROUNDS - 1), u(MAX_QA_ROUNDS - 1)
        self.senior_wait, self.senior_extra, self.senior_work = z(3)
        self.settle_wait, self.settle_work = z(2)
        self.rc4_apply, self.rc4_backlog = u(RC4_SLOTS), u(RC4_SLOTS)
        self.csat_noise, self.nps_noise = z(2)
        self.respond, self.has_comment, self.sent_delay, self.response_delay = u(4)
        self.comment_pick = u(2)


@dataclass(frozen=True)
class ClaimProfile:
    case_id: str
    lob: str
    channel: str
    region: str
    team: str
    amount: float
    fnol_at: datetime
    month_index: int  # 0 = first month of the period


class InsuranceClaimsGenerator:
    def __init__(self, pack: DomainPack, config: GeneratorConfig | None = None) -> None:
        self.pack = pack
        self.cfg = config or GeneratorConfig()
        self.cal = WorkCalendar.from_config(
            pack.calendar.workdays, pack.calendar.start, pack.calendar.end
        )
        self.tz = ZoneInfo(pack.case.timezone)
        self.sla_hours = pack.sla.target_hours
        assert pack.approval is not None, "the insurance pack declares an approval section"
        self.approval = pack.approval
        self.senior_threshold = pack.approval.senior_threshold_inr
        self.n_months = (self.cfg.end.year - self.cfg.start.year) * 12 + (
            self.cfg.end.month - self.cfg.start.month
        )

    # ------------------------------------------------------------------ profile

    def _profile(self, i: int, d: Draws) -> ClaimProfile:
        c = self.cfg
        lob = "motor" if d.lob < c.lob_weights["motor"] else "health"
        region = choose(c.region_weights, d.region)
        channel = choose(
            c.pune_channel_weights if region == "Pune" else c.channel_weights, d.channel
        )
        team = c.teams[min(int(d.team * len(c.teams)), len(c.teams) - 1)]
        median, sigma = (
            (c.motor_amount_median, c.motor_amount_sigma)
            if lob == "motor"
            else (c.health_amount_median, c.health_amount_sigma)
        )
        amount = round(min(max(lognormal(median, sigma, d.amount), c.amount_floor), c.amount_cap))

        w_start, w_end = c.window_start or c.start, c.window_end or c.end
        n_days = (w_end - w_start).days + 1
        day = w_start + timedelta(days=int(d.fnol_day * n_days))
        if d.fnol_mode < 0.85:  # most FNOLs arrive in working hours on a working day
            while day.weekday() not in self.cal.workdays:
                day = day + timedelta(days=1) if day < w_end else day - timedelta(days=3)
            start_h, end_h = self.cal.start.hour, self.cal.end.hour
            hour = start_h + d.fnol_hour * (end_h - start_h)
        else:  # app / call-centre claims at any time
            hour = d.fnol_hour * 24
        fnol_at = datetime.combine(day, time()) + timedelta(hours=hour)
        fnol_at = fnol_at.replace(second=0, microsecond=0)
        month_index = (day.year - c.start.year) * 12 + day.month - c.start.month
        return ClaimProfile(
            case_id=f"{self.pack.case.id_prefix}-{c.start.year}-{i + 1 + c.id_offset:06d}",
            lob=lob,
            channel=channel,
            region=region,
            team=team,
            amount=float(amount),
            fnol_at=fnol_at,
            month_index=month_index,
        )

    # --------------------------------------------------------------- simulation

    def simulate(self, p: ClaimProfile, d: Draws, disabled: frozenset[str]) -> SimResult:
        c, cal = self.cfg, self.cal
        events: list[SimEvent] = []
        triggered: set[str] = set()
        slot = 0

        def work_step(activity: str, resource: str, wait_h: float, work_h: float) -> None:
            nonlocal slot
            handoff = events[-1].end
            start = cal.add_working_hours(handoff, wait_h)
            if (
                "RC4" not in disabled
                and slot < RC4_SLOTS
                and handoff.weekday() == 4
                and c.rc4_from <= handoff.time() < cal.end
                and d.rc4_apply[slot] < c.rc4_probability
            ):
                lo, hi = c.rc4_backlog_hours
                monday = cal.add_working_hours(
                    cal.next_workday_start(handoff), lo + d.rc4_backlog[slot] * (hi - lo)
                )
                if monday > start:
                    start = monday
                    triggered.add("RC4")
            slot += 1
            end = cal.add_working_hours(start, work_h)
            events.append(SimEvent(activity, resource, start, end, hours(start - handoff)))

        def calendar_step(activity: str, resource: str, duration_h: float) -> None:
            start = events[-1].end
            events.append(
                SimEvent(activity, resource, start, start + timedelta(hours=duration_h), 0.0)
            )

        # FNOL (contact centre, 24x7)
        fnol_end = p.fnol_at + timedelta(minutes=10 + 30 * d.fnol_work)
        events.append(SimEvent("FNOL", "Contact Centre", p.fnol_at, fnol_end, 0.0))

        # Document check, with the missing-documents loop (RC2)
        work_step(
            "Document Check",
            "Intake Desk",
            lognormal(1.5, 0.6, d.dc_wait[0]),
            lognormal(0.5, 0.4, d.dc_work[0]),
        )
        broker_extra = (c.doc_request_broker_total - c.doc_request_base) / (1 - c.doc_request_base)
        for k in range(MAX_DOC_REQUESTS):
            factor = c.doc_request_repeat_factor**k
            base_hit = d.req_base[k] < c.doc_request_base * factor
            rc2_hit = (
                p.channel == "broker"
                and "RC2" not in disabled
                and d.req_extra[k] < broker_extra * factor
            )
            if not (base_hit or rc2_hit):
                break
            if rc2_hit and not base_hit:
                triggered.add("RC2")
            customer_h = min(max(lognormal(40.0, 0.5, d.req_duration[k]), 6.0), 200.0)
            calendar_step("Request Additional Documents", "Customer", customer_h)
            work_step(
                "Document Check",
                "Intake Desk",
                lognormal(1.5, 0.6, d.dc_wait[k + 1]),
                lognormal(0.5, 0.4, d.dc_work[k + 1]),
            )

        # Assessment: survey for motor, medical adjudication for health (same baseline: DC1)
        if p.lob == "motor":
            activity, resource = "Survey & Loss Assessment", "Surveyor Network"
        else:
            activity, resource = "Medical Adjudication", "Medical Team"
        work_step(
            activity,
            resource,
            lognormal(3.0, 0.7, d.assess_wait),
            lognormal(2.0, 0.5, d.assess_work),
        )

        # Verification ↔ QA loop (RC3)
        team_b_extra = (c.qa_reject_team_b_total - c.qa_reject_base) / (1 - c.qa_reject_base)
        for k in range(MAX_QA_ROUNDS):
            # A rejected file goes to the back of the team's queue, not straight back to work.
            ver_wait_median = 2.0 if k == 0 else c.rework_requeue_wait_median_h
            work_step(
                "Verification",
                p.team,
                lognormal(ver_wait_median, 0.6, d.ver_wait[k]),
                lognormal(1.5, 0.4, d.ver_work[k]),
            )
            work_step(
                "QA",
                "QA Desk",
                lognormal(1.0, 0.6, d.qa_wait[k]),
                lognormal(0.5, 0.4, d.qa_work[k]),
            )
            if k == MAX_QA_ROUNDS - 1:
                break
            factor = c.qa_reject_repeat_factor**k
            base_hit = d.qa_base[k] < c.qa_reject_base * factor
            rc3_hit = (
                p.team == "Team B"
                and "RC3" not in disabled
                and d.qa_extra[k] < team_b_extra * factor
            )
            if not (base_hit or rc3_hit):
                break
            if rc3_hit and not base_hit:
                triggered.add("RC3")

        # Senior approval above the threshold (RC1: understaffed, worsening over time)
        if p.amount > self.senior_threshold:
            wait = lognormal(c.senior_base_wait_median_h, 0.6, d.senior_wait)
            exempt = c.rc1_exempt_max_amount is not None and p.amount <= c.rc1_exempt_max_amount
            if "RC1" not in disabled and c.rc1_enabled and not exempt:
                progress = p.month_index / max(self.n_months, 1)
                median = c.rc1_extra_median_first_month_h + progress * (
                    c.rc1_extra_median_last_month_h - c.rc1_extra_median_first_month_h
                )
                wait += lognormal(median, 0.5, d.senior_extra)
                triggered.add("RC1")
            who = "Senior Adjuster 1" if d.senior_who < 0.5 else "Senior Adjuster 2"
            work_step("Senior Approval", who, wait, lognormal(1.0, 0.4, d.senior_work))

        work_step(
            "Settlement",
            "Finance Ops",
            lognormal(2.0, 0.6, d.settle_wait),
            lognormal(1.0, 0.4, d.settle_work),
        )
        last = events[-1].end
        events.append(SimEvent("Closed", "System", last, last, 0.0))
        return SimResult(events, triggered)

    # ----------------------------------------------------------------- feedback

    def _feedback(self, p: ClaimProfile, r: SimResult, d: Draws) -> dict[str, object]:
        c = self.cfg
        breached = r.cycle_hours > self.sla_hours
        n_requests = r.count("Request Additional Documents")
        rework = r.count("Verification") > 1
        senior = next((e for e in r.events if e.activity == "Senior Approval"), None)
        long_approval = senior is not None and senior.wait_hours > 48
        assess = r.events[
            next(
                i
                for i, e in enumerate(r.events)
                if e.activity in ("Survey & Loss Assessment", "Medical Adjudication")
            )
        ]
        cycle_days = r.cycle_hours / 24

        score = (
            4.5
            - 1.1 * breached
            - 0.5 * n_requests
            - 0.3 * rework
            - 0.4 * long_approval
            - 0.08 * max(0.0, cycle_days - 5)
            + 0.55 * d.csat_noise
        )
        csat = int(min(max(round(score), 1), 5))
        nps = int(min(max(round(2 * score + 0.6 + 1.1 * d.nps_noise), 0), 10))
        p_respond = c.response_rate_at_csat5 + c.response_rate_step * (5 - csat)
        responded = d.respond < p_respond

        sent_at = r.closed_at + timedelta(days=1 + 2 * d.sent_delay)
        themes: list[str] = []
        if n_requests:
            themes.append("documents")
        if long_approval:
            themes.append("approval_wait")
        if rework:
            themes.append("rework")
        if "RC4" in r.triggered:
            themes.append("weekend")
        if p.lob == "motor" and assess.wait_hours > 30:
            themes.append("surveyor")
        if breached and not themes:
            themes.append("slow_general")
        if not themes:
            themes.append("positive" if csat >= 4 else "neutral")

        comment = None
        if responded and d.has_comment < c.comment_probability:
            parts = [comments.pick(t, d.comment_pick[i]) for i, t in enumerate(themes[:2])]
            comment = " ".join(parts)

        return {
            "case_id": p.case_id,
            "sent_at": sent_at,
            "responded_at": sent_at + timedelta(hours=2 + 70 * d.response_delay)
            if responded
            else None,
            "csat": csat if responded else None,
            "nps": nps if responded else None,
            "comment": comment,
            "_true_csat": csat,
            "_true_nps": nps,
        }

    # ------------------------------------------------------------------ outputs

    def generate(self) -> "InsuranceClaimsDataset":
        cases, events, feedback, truth = [], [], [], []
        for i in range(self.cfg.n_claims):
            d = Draws(np.random.default_rng([self.cfg.seed, i + self.cfg.id_offset]))
            p = self._profile(i, d)
            full = self.simulate(p, d, NO_CAUSES)
            counterfactual = {cause: self.simulate(p, d, frozenset({cause})) for cause in CAUSES}
            baseline = self.simulate(p, d, ALL_CAUSES)

            local = lambda dt: dt.replace(tzinfo=self.tz)  # noqa: E731
            cases.append(
                {
                    "case_id": p.case_id,
                    "domain": self.pack.domain,
                    "amount": p.amount,
                    "opened_at": local(p.fnol_at),
                    "closed_at": local(full.closed_at),
                    "sla_due_at": local(p.fnol_at + timedelta(hours=self.sla_hours)),
                    "attributes": {
                        "line_of_business": p.lob,
                        "channel": p.channel,
                        "region": p.region,
                        "team": p.team,
                    },
                }
            )
            for seq, e in enumerate(full.events, start=1):
                events.append(
                    {
                        "case_id": p.case_id,
                        "seq": seq,
                        "activity": e.activity,
                        "resource": e.resource,
                        "started_at": local(e.start),
                        "ended_at": local(e.end),
                    }
                )
            fb = self._feedback(p, full, d)
            feedback.append(
                {k: (local(v) if isinstance(v, datetime) else v) for k, v in fb.items()}
            )

            breached = full.cycle_hours > self.sla_hours
            row: dict[str, object] = {
                "case_id": p.case_id,
                "cycle_hours": full.cycle_hours,
                "breached": breached,
                "breached_without_any_cause": baseline.cycle_hours > self.sla_hours,
            }
            for cause in CAUSES:
                cf = counterfactual[cause]
                row[f"{cause}_triggered"] = cause in full.triggered
                row[f"{cause}_delay_hours"] = full.cycle_hours - cf.cycle_hours
                row[f"{cause}_breach_attributable"] = breached and cf.cycle_hours <= self.sla_hours
            delegation = self.approval.delegation
            in_band = (
                delegation is not None
                and delegation.band_min_inr < p.amount <= delegation.band_max_inr
            )
            delegated = counterfactual["RC1"] if in_band else full
            row["delegation_cycle_hours"] = delegated.cycle_hours
            row["delegation_breached"] = delegated.cycle_hours > self.sla_hours
            truth.append(row)

        return InsuranceClaimsDataset(
            pack=self.pack,
            config=self.cfg,
            cases=pd.DataFrame(cases),
            events=pd.DataFrame(events),
            feedback=pd.DataFrame(feedback),
            truth=pd.DataFrame(truth),
            causes=CAUSES,
        )


class InsuranceClaimsDataset(GeneratedDataset):
    def summary(self) -> dict[str, object]:
        """Ground-truth summary: what a correct investigation should conclude."""
        t = self.joined_truth()
        n_breached = int(t["breached"].sum())
        causes = self.root_causes(t)

        bands = self.pack.dimension("amount_band").bands or []
        edges = [-math.inf] + [b.max for b in bands[:-1] if b.max is not None] + [math.inf]
        t["amount_band"] = pd.cut(t["amount"], edges, labels=[b.label for b in bands], right=True)
        dc1 = (
            t.groupby(["amount_band", "line_of_business"], observed=True)["cycle_hours"]
            .mean()
            .div(24)
            .round(2)
            .unstack()
        )
        pune = t[t["region"] == "Pune"]
        rest = t[t["region"] != "Pune"]
        fb = self.feedback

        delegation_avoided = int((t["breached"] & ~t["delegation_breached"]).sum())
        return {
            "domain": self.pack.domain,
            "seed": self.config.seed,
            "period": [self.config.start.isoformat(), self.config.end.isoformat()],
            "volumes": {
                "claims": len(self.cases),
                "events": len(self.events),
                "surveys_sent": len(fb),
                "survey_responses": int(fb["responded_at"].notna().sum()),
            },
            "sla_breach_rate": round(n_breached / len(t), 3),
            "breaches": n_breached,
            "breach_rate_without_any_planted_cause": round(
                float(t["breached_without_any_cause"].mean()), 3
            ),
            "root_causes": causes,
            "delegation_scenario": {
                "description": (
                    "Delegate ₹2L–₹5L approvals to Team Leads "
                    "(removes the RC1 queue delay in that band)"
                ),
                "breaches_avoided": delegation_avoided,
                "share_of_breaches_avoided": round(delegation_avoided / n_breached, 3),
                "claim_hours_saved": round(
                    float((t["cycle_hours"] - t["delegation_cycle_hours"]).sum()), 0
                ),
            },
            "decoys": {
                "DC1_mean_cycle_days_by_amount_band": {
                    str(band): row.dropna().to_dict() for band, row in dc1.iterrows()
                },
                "DC1_overall_mean_cycle_days": t.groupby("line_of_business")["cycle_hours"]
                .mean()
                .div(24)
                .round(2)
                .to_dict(),
                "DC2_pune": {
                    "claims": len(pune),
                    "breach_rate": round(float(pune["breached"].mean()), 3),
                    "breach_rate_other_regions": round(float(rest["breached"].mean()), 3),
                    "broker_share": round(float((pune["channel"] == "broker").mean()), 3),
                    "broker_share_other_regions": round(
                        float((rest["channel"] == "broker").mean()), 3
                    ),
                },
                "DC3_csat": {
                    "true_mean_csat_all_customers": round(float(fb["_true_csat"].mean()), 2),
                    "respondent_mean_csat": round(float(fb["csat"].mean()), 2),
                    "response_rate": round(float(fb["responded_at"].notna().mean()), 3),
                },
            },
        }
