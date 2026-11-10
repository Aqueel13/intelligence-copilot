"""Demo device: generate the NEXT month of synthetic claims, with executed actions applied.

The historical dataset ends in a fixed month, so nothing could otherwise show whether an
executed action works. This appends one more month from the same generator (trends continue:
an untreated senior-approval queue keeps getting worse) and applies the effect of every action
executed so far. It is clearly synthetic and recorded in intelligence.simulated_months.

How each executed action changes the generated world is declared next to each domain's
generator (ACTION_EFFECTS).
"""

from datetime import date

from dateutil.relativedelta import relativedelta
from pydantic import BaseModel
from sqlalchemy import Connection, text

from watchdog_backend.db import get_engine
from watchdog_backend.domain.pack import get_pack
from watchdog_backend.generator.loader import load_dataset
from watchdog_backend.generator.registry import NoGeneratorError, generate, generator_spec
from watchdog_backend.watch.engine import latest_period


class SimulatedMonth(BaseModel):
    month: str
    claims: int
    applied_actions: list[str]
    seed: int


class SimulationError(RuntimeError):
    pass


def simulate_next_month(conn: Connection) -> SimulatedMonth:
    pack = get_pack()
    try:
        spec = generator_spec(pack.domain)
    except NoGeneratorError as exc:
        raise SimulationError(str(exc)) from exc
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
        overrides.update(spec.action_effects.get(action_id, {}))
    offset = conn.execute(
        text("SELECT count(*) FROM operational.cases WHERE domain = :d"), {"d": pack.domain}
    ).scalar_one()
    seed = 42 + (start.year - 2026) * 12 + start.month
    conn.rollback()  # release the read transaction before the loader's own transaction

    dataset = generate(
        pack,
        seed=seed,
        n=spec.cases_per_month,
        window_start=start,
        window_end=end,
        id_offset=int(offset),
        **overrides,
    )
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
