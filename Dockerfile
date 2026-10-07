FROM ghcr.io/astral-sh/uv:0.12.21 AS uv

# TEMP-0.5.0-UNPUBLISHED-DEPENDENCIES: build the pyboy-rs wheel and source archive from the
# reviewed commit, because 0.1.1 is not on PyPI yet. Delete this stage and every line marked TEMP
# in the build stage once it is published; the image then needs no Rust toolchain.
FROM python:3.14-slim-trixie AS temp-pyboy-rs
ARG PYBOY_RS_REV=1f378907c17458a6108ceac94ea4be5889e638cc
ENV CARGO_HOME=/opt/cargo RUSTUP_HOME=/opt/rustup PATH=/opt/cargo/bin:$PATH
RUN apt-get update && apt-get install -y --no-install-recommends git curl ca-certificates gcc libc6-dev \
    && rm -rf /var/lib/apt/lists/* \
    && curl --proto '=https' --tlsv1.2 --fail --silent --show-error https://sh.rustup.rs | sh -s -- -y --profile minimal \
    && python -m pip install --no-cache-dir 'maturin>=1.9,<2'
RUN git init /src && cd /src \
    && git fetch --depth 1 https://github.com/afk-sapien/pyboy-rs "$PYBOY_RS_REV" \
    && git checkout --detach FETCH_HEAD \
    && maturin build --release --out /out && maturin sdist --out /out

FROM python:3.14-slim-trixie AS build
COPY --from=uv /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
WORKDIR /app
COPY pyproject.toml setup.py uv.lock README.md LICENSE THIRD_PARTY_NOTICES.md ./
COPY pokesim ./pokesim
COPY tools/bundle_dependency_sources.py ./tools/bundle_dependency_sources.py
COPY --from=temp-pyboy-rs /out /temp-pyboy-rs
# TEMP: git fetches pokesim-core (pure Python); the lock names git sources, so install the wheel built above.
RUN apt-get update && apt-get install -y --no-install-recommends git && rm -rf /var/lib/apt/lists/*
RUN uv sync --frozen --no-dev --no-editable --no-install-package pyboy-rs \
    && uv pip install --python .venv/bin/python /temp-pyboy-rs/*.whl \
    && .venv/bin/python tools/bundle_dependency_sources.py /notices --emulator-source /temp-pyboy-rs/pyboy_rs-0.1.1.tar.gz

FROM python:3.14-slim-trixie
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 \
    DATA_DIR=/data ROM_PATH=/roms/pokered.gb PORT=8000 HOST=0.0.0.0 \
    SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy PATH=/app/.venv/bin:$PATH
RUN apt-get update && apt-get upgrade -y \
    && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid 10001 pokesim \
    && useradd --uid 10001 --gid pokesim --no-create-home pokesim \
    && mkdir /data /roms && chown pokesim:pokesim /data
RUN python -m pip uninstall --yes pip \
    && rm -rf /usr/local/lib/python3.14/ensurepip
WORKDIR /app
COPY --from=build /app/.venv /app/.venv
COPY --from=build /notices /usr/share/pokesim
COPY --from=build /app/pokesim /usr/share/pokesim/source/pokesim
COPY pyproject.toml setup.py uv.lock LICENSE THIRD_PARTY_NOTICES.md /usr/share/pokesim/source/
COPY licenses /usr/share/pokesim/licenses
ARG VERSION=0.5.0
ARG REVISION=unknown
ENV POKESIM_REVISION=$REVISION
LABEL org.opencontainers.image.source="https://github.com/afk-sapien/PokeSim" \
      org.opencontainers.image.title="pokesim" \
      org.opencontainers.image.version=$VERSION \
      org.opencontainers.image.revision=$REVISION \
      org.opencontainers.image.licenses="MIT AND LGPL-3.0-only"
USER 10001:10001
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s CMD ["python", "-m", "pokesim.healthcheck", "--manager"]
CMD ["python", "-m", "pokesim", "serve", "--data-dir", "/data", "--host", "0.0.0.0"]
