# TEMP: remove before tagging 0.5.0

Core 0.2.0 and pyboy-rs 0.1.1 are not on PyPI yet. The commit titled "TEMP: ..." makes CI and the
Docker build work from pinned git commits. After both packages are published:

1. `git revert` the TEMP commit (or delete everything below by hand).
2. `uv lock` to regenerate `uv.lock` from PyPI. This is the only step that is not a deletion.
3. Delete this file.

What the TEMP commit adds:

- `pyproject.toml`: the `[tool.uv.sources]` block marked TEMP-0.5.0-UNPUBLISHED-DEPENDENCIES.
- `uv.lock`: the git-sourced entries for pokesim-core and pyboy-rs (regenerated in step 2).
- `tools/temp-unpublished-overrides.txt`: delete the file.
- `.github/workflows/ci.yml` and `.github/workflows/python-install.yml`: the top-level `env:` block
  with `UV_OVERRIDE`, and in ci.yml the two `--no-emit-package` flags on the pip-audit export.
- `Dockerfile`: the `temp-pyboy-rs` stage and every line marked TEMP in the build stage. Restore
  `RUN uv sync --frozen --no-dev --no-editable && .venv/bin/python tools/bundle_dependency_sources.py /notices`.
- This file.
