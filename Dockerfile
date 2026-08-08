# Production image: third-party deps and app code live in separate layers so
# routine code-only releases only pull a small app layer.
#
# Builder uses full bookworm (compilers available if a wheel needs building).
# Runtime uses slim to keep the pulled base small.
ARG PYTHON_BUILDER_IMAGE=python:3.11-bookworm
ARG PYTHON_RUNTIME_IMAGE=python:3.11-slim-bookworm

# -----------------------------------------------------------------------------
# Stage: third-party dependencies only (stable across code-only releases)
# -----------------------------------------------------------------------------
FROM ${PYTHON_BUILDER_IMAGE} AS deps

WORKDIR /build

ENV VIRTUAL_ENV=/opt/venv
ENV PATH="${VIRTUAL_ENV}/bin:${PATH}"

RUN python -m venv "${VIRTUAL_ENV}" \
    && pip install --no-cache-dir -U pip setuptools wheel

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# -----------------------------------------------------------------------------
# Stage: install the application, then export only app package files
# -----------------------------------------------------------------------------
FROM deps AS app

WORKDIR /src

COPY pyproject.toml requirements.txt MANIFEST.in README.md LICENSE ./
COPY embykeeper ./embykeeper
COPY embykeeperweb ./embykeeperweb
COPY embykeeperapi ./embykeeperapi

RUN pip install --no-cache-dir --no-deps . \
    && python - <<'PY'
import pathlib
import shutil
import sysconfig

sp = pathlib.Path(sysconfig.get_paths()["purelib"])
bindir = pathlib.Path(sysconfig.get_paths()["scripts"])
export = pathlib.Path("/export")
(export / "site-packages").mkdir(parents=True)
(export / "bin").mkdir(parents=True)

# Project installs as a single distribution named "embykeeper".
for path in sp.glob("embykeeper*"):
    if path.is_dir():
        shutil.copytree(path, export / "site-packages" / path.name)
    else:
        shutil.copy2(path, export / "site-packages" / path.name)

for name in ("embykeeper", "embykeeperweb", "embykeeperapi"):
    script = bindir / name
    if not script.exists():
        raise SystemExit(f"missing console script after install: {script}")
    shutil.copy2(script, export / "bin" / name)
PY

# -----------------------------------------------------------------------------
# Stage: runtime — large deps layer first, then tiny app overlay
# -----------------------------------------------------------------------------
FROM ${PYTHON_RUNTIME_IMAGE}

ENV VIRTUAL_ENV=/opt/venv
ENV PATH="${VIRTUAL_ENV}/bin:${PATH}"
ENV TZ="Asia/Shanghai"
ENV EK_IN_DOCKER="1"

# Large, stable layer shared by code-only releases.
COPY --from=deps /opt/venv /opt/venv

# Small layers that change when application code changes.
# python:3.11-* always uses lib/python3.11.
COPY --from=app /export/site-packages/ /opt/venv/lib/python3.11/site-packages/
COPY --from=app /export/bin/ /opt/venv/bin/
COPY scripts/docker-entrypoint.sh /entrypoint.sh

RUN chmod +x /entrypoint.sh \
        /opt/venv/bin/embykeeper \
        /opt/venv/bin/embykeeperweb \
        /opt/venv/bin/embykeeperapi \
    && mkdir -p /app \
    && touch /app/config.toml

WORKDIR /app

ENTRYPOINT ["/entrypoint.sh"]
