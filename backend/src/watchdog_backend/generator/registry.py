"""One synthetic-data generator per domain pack, behind a common interface.

`generate()` is what the CLI, the evaluation and the next-month simulator call; each domain's
module supplies how to build its generator and how executed actions change its world.
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from typing import Any

from watchdog_backend.domain.pack import DomainPack
from watchdog_backend.generator.common import GeneratedDataset


@dataclass(frozen=True)
class GeneratorSpec:
    build: Callable[
        ..., GeneratedDataset
    ]  # (pack, seed, n, window_start, window_end, id_offset, **overrides)
    default_cases: int
    cases_per_month: int  # for the "simulate next month" demo device
    action_effects: dict[str, dict[str, Any]]  # executed action -> generator config overrides


def _insurance() -> GeneratorSpec:
    from watchdog_backend.generator import insurance_claims as m

    def build(pack, seed, n, window_start, window_end, id_offset, **overrides):
        cfg = m.GeneratorConfig(
            n_claims=n,
            seed=seed,
            window_start=window_start,
            window_end=window_end,
            id_offset=id_offset,
            **overrides,
        )
        return m.InsuranceClaimsGenerator(pack, cfg).generate()

    return GeneratorSpec(build, 5000, 833, m.ACTION_EFFECTS)


def _procure_to_pay() -> GeneratorSpec:
    from watchdog_backend.generator import procure_to_pay as m

    def build(pack, seed, n, window_start, window_end, id_offset, **overrides):
        cfg = m.GeneratorConfig(
            n_invoices=n,
            seed=seed,
            window_start=window_start,
            window_end=window_end,
            id_offset=id_offset,
            **overrides,
        )
        return m.ProcureToPayGenerator(pack, cfg).generate()

    return GeneratorSpec(
        build, m.GeneratorConfig.n_invoices, m.INVOICES_PER_MONTH, m.ACTION_EFFECTS
    )


_SPECS: dict[str, Callable[[], GeneratorSpec]] = {
    "insurance_claims": _insurance,
    "procure_to_pay": _procure_to_pay,
}


class NoGeneratorError(LookupError):
    pass


def generator_spec(domain: str) -> GeneratorSpec:
    if domain not in _SPECS:
        raise NoGeneratorError(f"No synthetic-data generator for domain pack {domain!r}")
    return _SPECS[domain]()


def generate(
    pack: DomainPack,
    seed: int = 42,
    n: int | None = None,
    window_start: date | None = None,
    window_end: date | None = None,
    id_offset: int = 0,
    **overrides: Any,
) -> GeneratedDataset:
    spec = generator_spec(pack.domain)
    return spec.build(
        pack, seed, n or spec.default_cases, window_start, window_end, id_offset, **overrides
    )
