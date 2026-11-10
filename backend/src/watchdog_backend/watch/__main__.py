"""Run the monitors once, or on a schedule.

uv run python -m watchdog_backend.watch               # one run
uv run python -m watchdog_backend.watch --every 3600  # every hour (the watcher container)
"""

import argparse
import logging
import time

from sqlalchemy.exc import OperationalError, ProgrammingError

from watchdog_backend.db import get_engine
from watchdog_backend.domain.pack import available_domains, use_domain
from watchdog_backend.watch.engine import run_monitors

log = logging.getLogger("watchdog.watch")


def once(trigger: str) -> None:
    """Evaluate every enabled pack's monitors."""
    for domain in available_domains():
        with use_domain(domain), get_engine().connect() as conn:
            r = run_monitors(conn, trigger)
        log.info(
            "%s: period=%s evaluated=%d opened=%d updated=%d resolved=%d (%d ms)",
            domain,
            r.period,
            r.evaluated,
            r.opened,
            r.updated,
            r.resolved,
            r.duration_ms,
        )


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("--every", type=int, default=0, help="seconds between runs (0 = once)")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    if not args.every:
        once("manual")
        return
    while True:
        try:
            once("schedule")
        except (OperationalError, ProgrammingError) as exc:  # DB not ready / not migrated yet
            log.warning("skipped run: %s", str(exc).splitlines()[0])
        time.sleep(args.every)


if __name__ == "__main__":
    main()
