"""Load a generated dataset into the operational tables (replacing that domain's data)."""

import json

import pandas as pd
from sqlalchemy import Engine, text

from watchdog_backend.generator.insurance_claims import GeneratedDataset

_CASE_COLS = ("case_id", "domain", "amount", "opened_at", "closed_at", "sla_due_at", "attributes")
_EVENT_COLS = ("case_id", "seq", "activity", "resource", "started_at", "ended_at")
_FEEDBACK_COLS = ("case_id", "sent_at", "responded_at", "csat", "nps", "comment")


def _none_if_missing(value: object) -> object:
    """pandas represents missing values as NaN/NaT/None; Postgres needs NULL."""
    return None if pd.isna(value) else value


def load_dataset(engine: Engine, ds: GeneratedDataset) -> dict[str, int]:
    feedback = ds.public_feedback()
    with engine.begin() as conn:
        # Cascades to events and feedback.
        conn.execute(text("DELETE FROM operational.cases WHERE domain = :d"), {"d": ds.pack.domain})
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
    return {"cases": len(ds.cases), "events": len(ds.events), "feedback": len(feedback)}
