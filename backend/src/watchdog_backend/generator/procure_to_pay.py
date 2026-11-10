"""Synthetic Procure-to-Pay (invoice-to-pay) generator with planted root causes and decoys.

Same design as the insurance generator (see generator/common.py): every invoice draws all of
its randomness up front, so it can be re-simulated with one planted cause switched off; the
difference is an exact counterfactual.

Process (one case = one supplier invoice, SLA: paid within 10 calendar days of receipt):
  Invoice Received → Invoice Capture → 3-Way Match
    ↺ Invoice Capture again        (capture error found at matching)
    → Goods Receipt Confirmation   (goods not yet receipted in the ERP; goods categories only)
    ↺ Price Exception Resolution   (invoice price outside the PO tolerance; buyer resolves)
  → Budget Holder Approval → Finance Controller Approval (> ₹10L) → Payment Run → Payment Released

Planted causes:
  RC1  Chakan's stores post goods receipts late: more invoices find no GRN at matching, and
       they wait days for one
  RC2  Free-text (non-catalogue, non-contract) POs cause price exceptions
  RC3  The BPO Partner's invoice capture has a high error rate (re-capture loops)
  RC4  Since 1 July treasury runs payments weekly (Fridays) instead of twice weekly
Decoys:
  DC1  IT and professional services look slow, but only because they are mostly free-text
       POs (→ RC2)
  DC2  MSME suppliers look worse served, but only because their (paper) invoices mostly go to
       the BPO Partner (→ RC3)
"""

from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from watchdog_backend.domain.pack import DomainPack
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
NO_CAUSES: frozenset[str] = frozenset()
ALL_CAUSES: frozenset[str] = frozenset(CAUSES)
MAX_RECAPTURES = 2
MAX_PRICE_EXCEPTIONS = 2
GOODS = ("Raw materials", "Packaging", "MRO")
INVOICES_PER_MONTH = 1000

# How each catalogue action changes the world, in generator terms (the next-month simulator).
ACTION_EFFECTS: dict[str, dict[str, object]] = {
    "chakan_grn_discipline": {"rc1_enabled": False},
    "add_chakan_stores_clerk": {"rc1_enabled": False},
    "enforce_catalogue_buying": {"price_exception_free_text_total": 0.05},  # = the base rate
    "retrain_bpo_capture": {"capture_error_bpo_total": 0.04},  # = the base rate
    "restore_twice_weekly_runs": {"rc4_enabled": False},
}


@dataclass(frozen=True)
class GeneratorConfig:
    n_invoices: int = 6000
    seed: int = 42
    start: date = date(2026, 4, 1)
    end: date = date(2026, 9, 30)
    window_start: date | None = None
    window_end: date | None = None
    id_offset: int = 0

    plant_weights: dict[str, float] = field(
        default_factory=lambda: {
            "Chakan": 0.24,
            "Hosur": 0.22,
            "Manesar": 0.22,
            "Sanand": 0.18,
            "Sriperumbudur": 0.14,
        }
    )
    category_weights: dict[str, float] = field(
        default_factory=lambda: {
            "Raw materials": 0.30,
            "Packaging": 0.12,
            "MRO": 0.18,
            "Logistics": 0.14,
            "IT services": 0.14,
            "Professional services": 0.12,
        }
    )
    # DC1: services are mostly bought on free-text POs.
    free_text_share: dict[str, float] = field(
        default_factory=lambda: {
            "Raw materials": 0.04,
            "Packaging": 0.06,
            "MRO": 0.12,
            "Logistics": 0.10,
            "IT services": 0.80,
            "Professional services": 0.72,
        }
    )
    contract_share: dict[str, float] = field(
        default_factory=lambda: {
            "Raw materials": 0.62,
            "Packaging": 0.50,
            "MRO": 0.25,
            "Logistics": 0.60,
            "IT services": 0.10,
            "Professional services": 0.15,
        }
    )
    msme_share: dict[str, float] = field(
        default_factory=lambda: {
            "Raw materials": 0.35,
            "Packaging": 0.55,
            "MRO": 0.60,
            "Logistics": 0.45,
            "IT services": 0.30,
            "Professional services": 0.40,
        }
    )
    # DC2: MSME suppliers mostly send paper / PDF invoices, which the BPO Partner captures.
    ap_team_weights_msme: dict[str, float] = field(
        default_factory=lambda: {"AP Pune": 0.12, "AP Chennai": 0.13, "BPO Partner": 0.75}
    )
    ap_team_weights_large: dict[str, float] = field(
        default_factory=lambda: {"AP Pune": 0.48, "AP Chennai": 0.42, "BPO Partner": 0.10}
    )
    amount_median: dict[str, float] = field(
        default_factory=lambda: {
            "Raw materials": 350_000,
            "Packaging": 120_000,
            "MRO": 45_000,
            "Logistics": 80_000,
            "IT services": 250_000,
            "Professional services": 180_000,
        }
    )
    amount_sigma: float = 1.0
    amount_floor: float = 2_000
    amount_cap: float = 15_000_000
    controller_threshold: float = 1_000_000

    # RC3: capture errors found at matching
    capture_error_base: float = 0.04
    capture_error_bpo_total: float = 0.40
    capture_error_repeat_factor: float = 0.35
    recapture_wait_median_h: float = 18.0  # back of the capture queue

    # RC1: goods receipts at Chakan (goods categories only)
    rc1_enabled: bool = True
    grn_pending_base: float = 0.10
    grn_pending_chakan_total: float = 0.38
    grn_base_wait_median_h: float = 7.0  # working hours
    rc1_extra_wait_median_h: float = 26.0

    # RC2: price exceptions
    price_exception_base: float = 0.05
    price_exception_free_text_total: float = 0.55
    price_exception_repeat_factor: float = 0.30
    price_resolution_wait_median_h: float = 22.0

    # RC4: weekly payment runs from this date (twice weekly before / when disabled)
    rc4_enabled: bool = True
    rc4_from: date = date(2026, 7, 1)
    run_days: tuple[int, ...] = (1, 4)  # Tue, Fri (Monday = 0)
    rc4_run_days: tuple[int, ...] = (4,)
    run_time: time = time(11, 0)
    cutoff_time: time = time(17, 0)  # approved by 17:00 the working day before a run


class Draws:
    """Every random number one invoice can ever need, drawn in a fixed order."""

    def __init__(self, rng: np.random.Generator) -> None:
        u, z = rng.random, rng.standard_normal
        self.recv_mode, self.recv_day, self.recv_hour, self.recv_work = u(4)
        self.plant, self.category, self.po_type, self.size, self.team = u(5)
        self.amount = z()
        self.cap_wait, self.cap_work = z(MAX_RECAPTURES + 1), z(MAX_RECAPTURES + 1)
        self.cap_err_base, self.cap_err_extra = u(MAX_RECAPTURES), u(MAX_RECAPTURES)
        n_match = MAX_RECAPTURES + MAX_PRICE_EXCEPTIONS + 2
        self.match_wait, self.match_work = z(n_match), z(n_match)
        self.grn_base, self.grn_extra = u(2)
        self.grn_wait, self.grn_extra_wait, self.grn_work = z(3)
        self.pe_base, self.pe_extra = u(MAX_PRICE_EXCEPTIONS), u(MAX_PRICE_EXCEPTIONS)
        self.pe_wait, self.pe_work = z(MAX_PRICE_EXCEPTIONS), z(MAX_PRICE_EXCEPTIONS)
        self.appr_wait, self.appr_work, self.fc_wait, self.fc_work = z(4)
        self.pay_work = u()


@dataclass(frozen=True)
class InvoiceProfile:
    case_id: str
    plant: str
    category: str
    po_type: str
    vendor_size: str
    ap_team: str
    amount: float
    received_at: datetime
    month_index: int


class ProcureToPayGenerator:
    def __init__(self, pack: DomainPack, config: GeneratorConfig | None = None) -> None:
        self.pack = pack
        self.cfg = config or GeneratorConfig()
        self.cal = WorkCalendar.from_config(
            pack.calendar.workdays, pack.calendar.start, pack.calendar.end
        )
        self.tz = ZoneInfo(pack.case.timezone)
        self.sla_hours = pack.sla.target_hours

    # ------------------------------------------------------------------ profile

    def _profile(self, i: int, d: Draws) -> InvoiceProfile:
        c = self.cfg
        plant = choose(c.plant_weights, d.plant)
        category = choose(c.category_weights, d.category)
        free, contract = c.free_text_share[category], c.contract_share[category]
        po_type = (
            "free_text"
            if d.po_type < free
            else "contract"
            if d.po_type < free + contract
            else "catalogue"
        )
        size = "MSME" if d.size < c.msme_share[category] else "Large"
        team = choose(c.ap_team_weights_msme if size == "MSME" else c.ap_team_weights_large, d.team)
        amount = round(
            min(
                max(lognormal(c.amount_median[category], c.amount_sigma, d.amount), c.amount_floor),
                c.amount_cap,
            )
        )

        w_start, w_end = c.window_start or c.start, c.window_end or c.end
        n_days = (w_end - w_start).days + 1
        day = w_start + timedelta(days=int(d.recv_day * n_days))
        if d.recv_mode < 0.7:  # email / paper invoices are logged in working hours
            while day.weekday() not in self.cal.workdays:
                day = day + timedelta(days=1) if day < w_end else day - timedelta(days=3)
            start_h, end_h = self.cal.start.hour, self.cal.end.hour
            hour = start_h + d.recv_hour * (end_h - start_h)
        else:  # supplier portal uploads at any time
            hour = d.recv_hour * 24
        received = (datetime.combine(day, time()) + timedelta(hours=hour)).replace(
            second=0, microsecond=0
        )
        month_index = (day.year - c.start.year) * 12 + day.month - c.start.month
        return InvoiceProfile(
            case_id=f"{self.pack.case.id_prefix}-{c.start.year}-{i + 1 + c.id_offset:06d}",
            plant=plant,
            category=category,
            po_type=po_type,
            vendor_size=size,
            ap_team=team,
            amount=float(amount),
            received_at=received,
            month_index=month_index,
        )

    # --------------------------------------------------------------- payment runs

    def _next_run(self, approved: datetime, weekly: bool) -> datetime:
        """The first payment run whose cutoff (17:00 the working day before) the invoice
        makes."""
        c = self.cfg
        day = approved.date()
        for _ in range(30):
            day += timedelta(days=1)
            rc4 = weekly and day >= c.rc4_from
            if day.weekday() not in (c.rc4_run_days if rc4 else c.run_days):
                continue
            prev = day - timedelta(days=1)
            while prev.weekday() not in self.cal.workdays:
                prev -= timedelta(days=1)
            if approved <= datetime.combine(prev, c.cutoff_time):
                return datetime.combine(day, c.run_time)
        raise RuntimeError("no payment run found")  # pragma: no cover

    # --------------------------------------------------------------- simulation

    def simulate(self, p: InvoiceProfile, d: Draws, disabled: frozenset[str]) -> SimResult:
        c, cal = self.cfg, self.cal
        events: list[SimEvent] = []
        triggered: set[str] = set()
        match_i = 0

        def work_step(activity: str, resource: str, wait_h: float, work_h: float) -> None:
            handoff = events[-1].end
            start = cal.add_working_hours(handoff, wait_h)
            end = cal.add_working_hours(start, work_h)
            events.append(SimEvent(activity, resource, start, end, hours(start - handoff)))

        def match() -> None:
            nonlocal match_i
            work_step(
                "3-Way Match",
                "AP Matching",
                lognormal(3.0, 0.6, d.match_wait[match_i]),
                lognormal(0.2, 0.4, d.match_work[match_i]),
            )
            match_i += 1

        received_end = p.received_at + timedelta(minutes=5 + 20 * d.recv_work)
        events.append(SimEvent("Invoice Received", "Supplier", p.received_at, received_end, 0.0))

        # Capture, and re-capture when matching finds a data-entry error (RC3)
        bpo_extra = (c.capture_error_bpo_total - c.capture_error_base) / (1 - c.capture_error_base)
        work_step(
            "Invoice Capture",
            p.ap_team,
            lognormal(5.0, 0.7, d.cap_wait[0]),
            lognormal(0.25, 0.4, d.cap_work[0]),
        )
        match()
        for k in range(MAX_RECAPTURES):
            factor = c.capture_error_repeat_factor**k
            base_hit = d.cap_err_base[k] < c.capture_error_base * factor
            rc3_hit = (
                p.ap_team == "BPO Partner"
                and "RC3" not in disabled
                and d.cap_err_extra[k] < bpo_extra * factor
            )
            if not (base_hit or rc3_hit):
                break
            if rc3_hit and not base_hit:
                triggered.add("RC3")
            work_step(
                "Invoice Capture",
                p.ap_team,
                lognormal(c.recapture_wait_median_h, 0.6, d.cap_wait[k + 1]),
                lognormal(0.3, 0.4, d.cap_work[k + 1]),
            )
            match()

        # Goods not yet receipted in the ERP (RC1: Chakan's stores post late)
        if p.category in GOODS:
            rc1 = p.plant == "Chakan" and "RC1" not in disabled and c.rc1_enabled
            chakan_extra = (c.grn_pending_chakan_total - c.grn_pending_base) / (
                1 - c.grn_pending_base
            )
            base_hit = d.grn_base < c.grn_pending_base
            rc1_hit = rc1 and d.grn_extra < chakan_extra
            if base_hit or rc1_hit:
                wait = lognormal(c.grn_base_wait_median_h, 0.6, d.grn_wait)
                if rc1:
                    wait += lognormal(c.rc1_extra_wait_median_h, 0.5, d.grn_extra_wait)
                    triggered.add("RC1")
                work_step(
                    "Goods Receipt Confirmation",
                    f"Stores {p.plant}",
                    wait,
                    lognormal(0.3, 0.4, d.grn_work),
                )
                match()

        # Price outside the PO tolerance (RC2: free-text POs have no agreed price)
        ft_extra = (c.price_exception_free_text_total - c.price_exception_base) / (
            1 - c.price_exception_base
        )
        for k in range(MAX_PRICE_EXCEPTIONS):
            factor = c.price_exception_repeat_factor**k
            base_hit = d.pe_base[k] < c.price_exception_base * factor
            rc2_hit = (
                p.po_type == "free_text"
                and "RC2" not in disabled
                and d.pe_extra[k] < ft_extra * factor
            )
            if not (base_hit or rc2_hit):
                break
            if rc2_hit and not base_hit:
                triggered.add("RC2")
            work_step(
                "Price Exception Resolution",
                "Procurement Buyer",
                lognormal(c.price_resolution_wait_median_h, 0.6, d.pe_wait[k]),
                lognormal(1.5, 0.4, d.pe_work[k]),
            )
            match()

        work_step(
            "Invoice Approval",
            "Budget Holder",
            lognormal(9.0, 0.7, d.appr_wait),
            lognormal(0.2, 0.4, d.appr_work),
        )
        if p.amount > c.controller_threshold:
            work_step(
                "Finance Controller Approval",
                "Finance Controller",
                lognormal(7.0, 0.6, d.fc_wait),
                lognormal(0.3, 0.4, d.fc_work),
            )

        # Payment run (RC4: weekly from rc4_from)
        approved = events[-1].end
        weekly = "RC4" not in disabled and c.rc4_enabled
        run = self._next_run(approved, weekly)
        if weekly and run != self._next_run(approved, False):
            triggered.add("RC4")
        run_end = run + timedelta(minutes=30 + 60 * d.pay_work)
        events.append(SimEvent("Payment Run", "Treasury", run, run_end, hours(run - approved)))
        events.append(SimEvent("Payment Released", "Bank", run_end, run_end, 0.0))
        return SimResult(events, triggered)

    # ------------------------------------------------------------------ outputs

    def generate(self) -> "ProcureToPayDataset":
        cases, events, truth = [], [], []
        for i in range(self.cfg.n_invoices):
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
                    "opened_at": local(p.received_at),
                    "closed_at": local(full.closed_at),
                    "sla_due_at": local(p.received_at + timedelta(hours=self.sla_hours)),
                    "attributes": {
                        "plant": p.plant,
                        "category": p.category,
                        "po_type": p.po_type,
                        "ap_team": p.ap_team,
                        "vendor_size": p.vendor_size,
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
            truth.append(row)

        return ProcureToPayDataset(
            pack=self.pack,
            config=self.cfg,
            cases=pd.DataFrame(cases),
            events=pd.DataFrame(events),
            feedback=pd.DataFrame(),
            truth=pd.DataFrame(truth),
            causes=CAUSES,
        )


class ProcureToPayDataset(GeneratedDataset):
    def summary(self) -> dict[str, object]:
        """Ground-truth summary: what a correct investigation should conclude."""
        t = self.joined_truth()
        n_breached = int(t["breached"].sum())

        def rate(df: pd.DataFrame) -> float:
            return round(float(df["breached"].mean()), 3) if len(df) else 0.0

        def within(df: pd.DataFrame, by: str) -> dict[str, float]:
            return {
                str(k): round(float(v), 3) for k, v in df.groupby(by)["breached"].mean().items()
            }

        services = t["category"].isin(["IT services", "Professional services"])
        msme = t["vendor_size"] == "MSME"
        months = t.assign(month=pd.to_datetime(t["opened_at"]).dt.strftime("%Y-%m"))
        return {
            "domain": self.pack.domain,
            "seed": self.config.seed,  # type: ignore[attr-defined]
            "period": [self.config.start.isoformat(), self.config.end.isoformat()],  # type: ignore[attr-defined]
            "volumes": {"invoices": len(self.cases), "events": len(self.events)},
            "sla_breach_rate": round(n_breached / len(t), 3),
            "breaches": n_breached,
            "breach_rate_without_any_planted_cause": round(
                float(t["breached_without_any_cause"].mean()), 3
            ),
            "root_causes": self.root_causes(t),
            "breach_rate_by_month": within(months, "month"),
            "decoys": {
                "DC1_services": {
                    "breach_rate": rate(t[services]),
                    "breach_rate_other_categories": rate(t[~services]),
                    "free_text_share": round(
                        float((t.loc[services, "po_type"] == "free_text").mean()), 3
                    ),
                    "breach_rate_by_po_type_services": within(t[services], "po_type"),
                    "breach_rate_by_po_type_other": within(t[~services], "po_type"),
                },
                "DC2_msme": {
                    "breach_rate": rate(t[msme]),
                    "breach_rate_large": rate(t[~msme]),
                    "bpo_share": round(float((t.loc[msme, "ap_team"] == "BPO Partner").mean()), 3),
                    "breach_rate_by_ap_team_msme": within(t[msme], "ap_team"),
                    "breach_rate_by_ap_team_large": within(t[~msme], "ap_team"),
                },
            },
        }
