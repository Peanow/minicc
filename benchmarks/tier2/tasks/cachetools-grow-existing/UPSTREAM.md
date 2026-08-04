# Upstream provenance

- Repository: https://github.com/tkem/cachetools
- Base commit: `13bb86a55e36e501cf0b3e4c35db516ed9409fd7`
- Upstream fix: https://github.com/tkem/cachetools/pull/408
- Related issue: https://github.com/tkem/cachetools/issues/405
- License: MIT

This fixture is a curated snapshot of the package, tests, and build metadata at
the PR's pre-fix commit. The upstream regression assertions are intentionally
excluded from the Agent workspace and replaced by an evaluator-only check.
The protected root `conftest.py` only exposes the upstream `src` layout so the
snapshot can be tested without installing packages or accessing the network.
