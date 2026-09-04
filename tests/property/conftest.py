"""Hypothesis profiles for the property tier (ADR 0069).

Three profiles, and the difference between them is *how many* examples
run, never *which* ones:

- **`ci`** — what the per-PR gate runs. `derandomize=True`, so the
  examples are a pure function of the test's name and the strategy;
  a failure reported by CI reproduces byte-for-byte on a laptop from
  the node id alone, with no seed to copy out of a log that may have
  been truncated.
- **`dev`** — the local default. Identical except that it runs more
  examples, because a developer waiting on one file can afford what a
  nine-job CI matrix cannot.
- **`explore`** — opt-in fuzzing: randomized, many more examples, and
  the example database switched back on so a failure it finds is
  replayed first on the next run. This is the profile to reach for
  when *hunting*; it is deliberately not what any gate runs, because a
  gate whose input set changes between runs cannot say whether a fix
  worked.

`derandomize=True` in the two gating profiles is the whole reason this
tier is allowed to be a gate at all. It also implies `database=None`
in Hypothesis — a stored counterexample would make one machine's run
differ from another's, which is exactly what derandomization exists to
prevent — so the setting is not passed alongside it (Hypothesis raises
`InvalidArgument` if it is).

`deadline=None` everywhere, per `planning/08-assurance/02-STANDARDS.md`
§6. A per-example deadline measures wall clock on a shared runner, so
it fails on machine load rather than on anything about the code; the
real ceiling is `pyproject.toml`'s 60-second per-test timeout, which
applies uniformly and reports the test that hung.

Hypothesis's own storage lives in `.hypothesis/`, which it creates
containing a `.gitignore` of `*`, so nothing here has to be added to
the repository's ignore rules for `git status` to stay clean.
"""

from __future__ import annotations

import os
from typing import Final

from hypothesis import Verbosity, settings

#: Read before anything else, so a developer can run the gate's exact
#: example set locally (`HYPOTHESIS_PROFILE=ci pytest -m property`)
#: without pretending to be CI.
PROFILE_ENV: Final = "HYPOTHESIS_PROFILE"

#: How CI announces itself. GitHub Actions sets it unconditionally, and
#: Hypothesis reads the same variable for its own built-in `ci` profile.
CI_ENV: Final = "CI"

CI_PROFILE: Final = "ci"
DEV_PROFILE: Final = "dev"
EXPLORE_PROFILE: Final = "explore"

#: Chosen against the tier's measured wall clock, not by taste: the
#: acceptance criterion for this work order is that `pytest -m property`
#: finishes inside 60 s, and a tier that misses it gets run less often,
#: which costs more than the examples buy.
CI_MAX_EXAMPLES: Final = 100
DEV_MAX_EXAMPLES: Final = 200
EXPLORE_MAX_EXAMPLES: Final = 2_000

settings.register_profile(
    CI_PROFILE,
    max_examples=CI_MAX_EXAMPLES,
    derandomize=True,
    deadline=None,
    # Prints the `@reproduce_failure` blob with a failure, so a
    # counterexample can be pinned into a regression test verbatim
    # instead of retyped from the shrunk repr.
    print_blob=True,
)

settings.register_profile(
    DEV_PROFILE,
    max_examples=DEV_MAX_EXAMPLES,
    derandomize=True,
    deadline=None,
    print_blob=True,
)

settings.register_profile(
    EXPLORE_PROFILE,
    max_examples=EXPLORE_MAX_EXAMPLES,
    derandomize=False,
    deadline=None,
    print_blob=True,
    verbosity=Verbosity.normal,
)


def _selected_profile() -> str:
    """Name the profile this session runs under.

    An explicit `HYPOTHESIS_PROFILE` always wins — including over the
    CI detection — because the one thing a developer chasing a CI
    failure needs is the ability to say "run it the way the runner
    did".
    """
    requested = os.environ.get(PROFILE_ENV, "").strip()
    if requested:
        return requested
    return CI_PROFILE if os.environ.get(CI_ENV, "").strip() else DEV_PROFILE


# Loaded at conftest import rather than in `pytest_configure`: the
# `@settings` decorators inside the test modules are evaluated during
# collection, and a profile loaded after that point would be ignored by
# every test that had already been imported.
settings.load_profile(_selected_profile())
