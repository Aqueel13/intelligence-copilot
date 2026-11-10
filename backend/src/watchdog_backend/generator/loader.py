"""Load a generated dataset into the operational tables (replacing that domain's data)."""

import json

import pandas as pd
from sqlalchemy import Engine, text

from watchdog_backend.generator.common import FEEDBACK_COLUMNS, GeneratedDataset

_CASE_COLS = ("case_id", "domain", "amount", "opened_at", "closed_at", "sla_due_at", "attributes")
_EVENT_COLS = ("case_id", "seq", "activity", "resource", "started_at", "ended_at")
_FEEDBACK_COLS = FEEDBACK_COLUMNS


def _none_if_missing(value: object) -> object:
    """pandas represents missing values as NaN/NaT/None; Postgres needs NULL."""
    return None if pd.isna(value) else value


def load_dataset(engine: Engine, ds: GeneratedDataset, replace: bool = True) -> dict[str, int]:
    """Load a dataset. `replace=True` swaps out the domain's data; False appends (new cases
    must have new ids, e.g. a simulated month)."""
    feedback = ds.public_feedback()
    with engine.begin() as conn:
        if replace:  # cascades to events and feedback; simulated months no longer exist
            conn.execute(
                text("DELETE FROM operational.cases WHERE domain = :d"), {"d": ds.pack.domain}
            )
            conn.execute(
                text("DELETE FROM intelligence.simulated_months WHERE domain = :d"),
                {"d": ds.pack.domain},
            )
        raw = conn.connection.driver_connection
        with raw.cursor() as cur:
            with cur.copy(f"COPY operational.cases ({', '.join(_CASE_COLS)}) FROM STDIN") as cp:
                for r in ds.cases.itertuples(index=False):
                    cp.write_row(
                        [*(getattr(r, c) for c in _CASE_COLS[:-1]), json.dumps(r.attributes)]
                    )
            with cur.copy(f"COPY operational.events ({', '.join(_EVENT_COLS)}) FROM STDIN") as cp:
                for r in ds.events.itertuples(index=False):
                    cp.write_row([getattr(r, c) for c in _EVENT_COLS])
            with cur.copy(
                f"COPY operational.feedback ({', '.join(_FEEDBACK_COLS)}) FROM STDIN"
            ) as cp:
                for r in feedback.itertuples(index=False):
                    row = [_none_if_missing(getattr(r, c)) for c in _FEEDBACK_COLS]
                    row[3] = None if row[3] is None else int(row[3])  # csat
                    row[4] = None if row[4] is None else int(row[4])  # nps
                    cp.write_row(row)
    # Derived data and planner statistics must follow every load: case_facts reads per-case
    # activity counts from a materialized view (see migration 0008).
    with engine.begin() as conn:
        conn.execute(text("REFRESH MATERIALIZED VIEW operational.case_activity_counts"))
        conn.execute(
            text(
                "ANALYZE operational.cases, operational.events, operational.feedback, "
                "operational.case_activity_counts"
            )
        )
    return {"cases": len(ds.cases), "events": len(ds.events), "feedback": len(feedback)}
