# TEMP: remove before the 0.5.0 release

The pokesim-core 0.2.0 and pyboy-rs 0.1.1 GitHub releases do not exist yet. The commit that adds this
file points `pyproject.toml`, `uv.lock` and the Dockerfile at copies of the same wheels stored in
`tools/temp-wheels/` (pyboy-rs built by the pyboy-rs `Wheels` workflow on commit 45c2fe7, Core built
from commit a4ecd8a), so CI can run. Revert that commit once the real releases exist, then run
`uv lock` against them. The pull request description has the full steps.
