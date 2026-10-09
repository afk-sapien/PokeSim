# TEMP: remove before the 0.5.0 release

The pokesim-core v0.6.0 GitHub release does not exist yet. The commit that adds this file stores the
Core 0.6.0 wheel (built from pokesim-core commit a7091d6) in `tools/temp-wheels/`. `pyproject.toml`
names its raw branch URL with the wheel hash, `[tool.uv.sources]` locks it from the stored copy and the
Dockerfile copies it into the build. Once the real release exists, point the Core requirement at the
release wheel with its `#sha256=` fragment, delete `[tool.uv.sources]`, `tools/temp-wheels/`, the
Dockerfile COPY line and this file, then run `uv lock`.
