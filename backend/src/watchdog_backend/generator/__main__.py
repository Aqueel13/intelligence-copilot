"""Generate synthetic data, write it to disk with ground truth, and optionally load it.

uv run python -m watchdog_backend.generator                 # write files only
uv run python -m watchdog_backend.generator --load          # write files and load into DB
uv run python -m watchdog_backend.generator --seed 7 --claims 1000 --load
"""

import argparse
import json
import time
from pathlib import Path

from watchdog_backend.config import get_settings
from watchdog_backend.db import get_engine
from watchdog_backend.domain.pack import get_pack
from watchdog_backend.generator.insurance_claims import GeneratorConfig, InsuranceClaimsGenerator
from watchdog_backend.generator.loader import load_dataset


def main() -> None:
    settings = get_settings()
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--claims", type=int, default=5000)
    parser.add_argument(
        "--out",
        type=Path,
        default=Path(settings.datasets_dir) / settings.domain_pack,
        help="output directory (default: %(default)s)",
    )
    parser.add_argument("--load", action="store_true", help="load into the database")
    args = parser.parse_args()

    if settings.domain_pack != "insurance_claims":
        raise SystemExit(f"No generator for domain pack {settings.domain_pack!r} yet")

    started = time.perf_counter()
    ds = InsuranceClaimsGenerator(
        get_pack(), GeneratorConfig(n_claims=args.claims, seed=args.seed)
    ).generate()
    ds.write(args.out)
    print(
        f"Generated {len(ds.cases):,} claims, {len(ds.events):,} events "
        f"in {time.perf_counter() - started:.1f}s → {args.out}"
    )

    if args.load:
        counts = load_dataset(get_engine(), ds)
        print(f"Loaded into database: {json.dumps(counts)}")

    s = ds.summary()
    print(
        f"\nGround truth: SLA breach rate {s['sla_breach_rate']:.1%} "
        f"(without planted causes: {s['breach_rate_without_any_planted_cause']:.1%})"
    )
    for cause, v in s["root_causes"].items():  # type: ignore[union-attr]
        print(
            f"  {cause}: {v['share_of_breaches']:.1%} of breaches, "
            f"{v['claims_affected']:,} claims affected"
        )


if __name__ == "__main__":
    main()
