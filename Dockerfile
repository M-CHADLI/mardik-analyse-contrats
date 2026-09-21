# syntax=docker/dockerfile:1

# --- Etage de construction : on resout les dependances une fois, sans outillage de dev.
FROM python:3.12-slim AS construction

COPY --from=ghcr.io/astral-sh/uv:0.5.11 /uv /bin/uv

WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy

COPY pyproject.toml uv.lock ./
COPY src/ src/
RUN uv sync --frozen --no-dev --no-editable


# --- Etage d'execution : image minimale, utilisateur non privilegie.
FROM python:3.12-slim AS execution

# Identifiant de la version livree, injecte au build par la chaine LLMOps. C'est lui qui
# rend verifiable l'exigence « on peut identifier quelle version sert quel trafic ».
ARG MARDIK_VERSION=dev-local
ENV MARDIK_VERSION=${MARDIK_VERSION} \
    PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/src

RUN useradd --uid 10001 --create-home --shell /usr/sbin/nologin mardik

WORKDIR /app
COPY --from=construction /app/.venv /app/.venv
COPY src/ src/
COPY eval/ eval/
COPY web/ web/
COPY besoin_client.md ./

# Les signaux et le journal de pilotage sont ecrits ici : volume pour les conserver
# entre deux versions, condition pour qu'un rollback garde l'historique.
RUN mkdir -p /app/donnees && chown -R mardik:mardik /app
VOLUME ["/app/donnees"]

USER mardik
EXPOSE 8000

HEALTHCHECK --interval=15s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8000/sante', timeout=4).status==200 else 1)"

CMD ["uvicorn", "mardik.api.app:app", "--host", "0.0.0.0", "--port", "8000"]
