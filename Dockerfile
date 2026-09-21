FROM ghcr.io/astral-sh/uv:0.12.17 AS uv
FROM python:3.14-slim-trixie AS build
COPY --from=uv /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
WORKDIR /app
COPY pyproject.toml setup.py uv.lock README.md LICENSE THIRD_PARTY_NOTICES.md ./
COPY pokesim ./pokesim
COPY tools/bundle_dependency_sources.py ./tools/bundle_dependency_sources.py
RUN uv sync --frozen --no-dev --no-editable \
    && .venv/bin/python tools/bundle_dependency_sources.py /notices

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
ARG VERSION=0.2.1
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
