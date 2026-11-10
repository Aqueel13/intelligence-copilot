"""Generate synthetic data, write it to disk with ground truth, and optionally load it.

uv run python -m watchdog_backend.generator                       # every enabled pack, files only
uv run python -m watchdog_backend.generator --load                # …and load into the database
uv run python -m watchdog_backend.generator --domain procure_to_pay --seed 7 --cases 1000 --load
"""

import argparse
import json
import time
from pathlib import Path

from watchdog_backend.config import get_settings
from watchdog_backend.db import get_engine
from watchdog_backend.domain.pack import available_domains, get_pack
from watchdog_backend.generator.loader import load_dataset
from watchdog_backend.generator.registry import generate


def run(domain: str, seed: int, n: int | None, out: Path, load: bool) -> None:
    pack = get_pack(domain)
    started = time.perf_counter()
    ds = generate(pack, seed=seed, n=n)
    ds.write(out)
    print(
        f"[{domain}] generated {len(ds.cases):,} {pack.case.labels}, {len(ds.events):,} events "
        f"in {time.perf_counter() - started:.1f}s → {out}"
    )
    if load:
        counts = load_dataset(get_engine(), ds)
        print(f"[{domain}] loaded into database: {json.dumps(counts)}")

    s = ds.summary()
    print(
        f"[{domain}] ground truth: SLA breach rate {s['sla_breach_rate']:.1%} "
        f"(without planted causes: {s['breach_rate_without_any_planted_cause']:.1%})"
    )
    for cause, v in s["root_causes"].items():  # type: ignore[union-attr]
        print(
            f"  {cause}: {v['share_of_breaches']:.1%} of breaches, "
            f"{v['cases_affected']:,} {pack.case.labels} affected"
        )


def main() -> None:
    settings = get_settings()
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("--domain", default="all", help="a pack name, or all (default)")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--cases", type=int, default=None, help="default: the generator's own")
    parser.add_argument("--out", type=Path, default=None, help="default: <datasets_dir>/<domain>")
    parser.add_argument("--load", action="store_true", help="load into the database")
    args = parser.parse_args()

    domains = available_domains() if args.domain == "all" else [args.domain]
    for domain in domains:
        out = args.out or Path(settings.datasets_dir) / domain
        run(domain, args.seed, args.cases, out, args.load)


if __name__ == "__main__":
    main()
