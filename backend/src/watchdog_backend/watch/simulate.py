"""Demo device: generate the NEXT month of synthetic claims, with executed actions applied.

The historical dataset ends in a fixed month, so nothing could otherwise show whether an
executed action works. This appends one more month from the same generator (trends continue:
an untreated senior-approval queue keeps getting worse) and applies the effect of every action
executed so far. It is clearly synthetic and recorded in intelligence.simulated_months.

Only the Insurance Claims generator exists, so the action → generator mapping lives here.
"""

from datetime import date

from dateutil.relativedelta import relativedelta
from pydantic import BaseModel
from sqlalchemy import Connection, text

from watchdog_backend.db import get_engine
from watchdog_backend.domain.pack import get_pack
from watchdog_backend.generator.insurance_claims import GeneratorConfig, InsuranceClaimsGenerator
from watchdog_backend.generator.loader import load_dataset
from watchdog_backend.watch.engine import latest_period

CLAIMS_PER_MONTH = 833

# How each catalogue action changes the world, in generator terms.
EFFECTS = {
    "delegate_mid_value_approvals": {"rc1_exempt_max_amount": 500_000},
    "add_senior_adjuster_capacity": {"rc1_enabled": False},
    "enforce_broker_checklist": {"doc_request_broker_total": 0.06},  # = the base rate
    "retrain_team_b": {"qa_reject_team_b_total": 0.05},  # = the base rate
    "saturday_rota": {"rc4_probability": 0.0},
}


class SimulatedMonth(BaseModel):
    month: str
    claims: int
    applied_actions: list[str]
    seed: int


class SimulationError(RuntimeError):
    pass


def simulate_next_month(conn: Connection) -> SimulatedMonth:
    pack = get_pack()
    if pack.domain != "insurance_claims":
        raise SimulationError(f"No simulator for domain pack '{pack.domain}'")
    latest = latest_period(conn)
    if latest is None:
        raise SimulationError("No data loaded yet: run `make seed` first.")
    start = date.fromisoformat(f"{latest}-01") + relativedelta(months=1)
    end = start + relativedelta(months=1, days=-1)
    month = start.strftime("%Y-%m")

    applied = list(
        conn.execute(
            text("""SELECT DISTINCT action_id FROM operations.action_requests
                    WHERE domain = :d AND status = 'executed' ORDER BY action_id"""),
            {"d": pack.domain},
        ).scalars()
    )
    overrides: dict[str, object] = {}
    for action_id in applied:
        overrides.update(EFFECTS.get(action_id, {}))
    offset = conn.execute(
        text("SELECT count(*) FROM operational.cases WHERE domain = :d"), {"d": pack.domain}
    ).scalar_one()
    seed = 42 + (start.year - 2026) * 12 + start.month
    conn.rollback()  # release the read transaction before the loader's own transaction

    cfg = GeneratorConfig(
        n_claims=CLAIMS_PER_MONTH,
        seed=seed,
        window_start=start,
        window_end=end,
        id_offset=int(offset),
        **overrides,
    )
    dataset = InsuranceClaimsGenerator(pack, cfg).generate()
    load_dataset(get_engine(), dataset, replace=False)
    conn.execute(
        text("""INSERT INTO intelligence.simulated_months
                  (month, domain, claims, applied_actions, seed)
                VALUES (:m, :d, :n, :a, :s)"""),
        {"m": month, "d": pack.domain, "n": len(dataset.cases), "a": applied, "s": seed},
    )
    conn.commit()
    return SimulatedMonth(
        month=month, claims=len(dataset.cases), applied_actions=applied, seed=seed
    )
