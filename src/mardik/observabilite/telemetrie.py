"""Traces OpenTelemetry et journalisation structuree.

Chaque requete devient un span portant la version du modele et la version livree, ce qui
rend une analyse tracable de bout en bout : on peut relier une reponse au segment qui l'a
produite, au modele qui l'a servie et a la configuration en vigueur a cet instant.

L'export est desactivable (`MARDIK_OTEL_ACTIF=0`) pour que les tests et la chaine
d'integration n'aient besoin d'aucun collecteur.
"""

from __future__ import annotations

import logging
from contextlib import contextmanager
from typing import Iterator

import structlog
from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.trace import Span

from mardik.config import config, version_livree

_initialise = False


def initialiser() -> None:
    """Installe le tracer et la journalisation structuree. Idempotent."""
    global _initialise
    if _initialise:
        return
    _initialise = True

    logging.basicConfig(level=getattr(logging, config.log_level.upper(), logging.INFO))
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.JSONRenderer(ensure_ascii=False),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(logging, config.log_level.upper(), logging.INFO)
        ),
    )

    if not config.mardik_otel_actif:
        return

    fournisseur = TracerProvider(
        resource=Resource.create(
            {
                "service.name": config.otel_service_name,
                "service.version": version_livree(),
            }
        )
    )
    try:
        from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter

        fournisseur.add_span_processor(
            BatchSpanProcessor(
                OTLPSpanExporter(endpoint=config.otel_exporter_otlp_endpoint, insecure=True)
            )
        )
    except Exception:  # noqa: BLE001 — l'absence de collecteur ne doit jamais bloquer l'API
        structlog.get_logger().warning("otel_export_indisponible")

    trace.set_tracer_provider(fournisseur)


def logger() -> structlog.BoundLogger:
    return structlog.get_logger()


@contextmanager
def span(nom: str, **attributs: object) -> Iterator[Span | None]:
    """Ouvre un span nomme portant les attributs passes."""
    if not config.mardik_otel_actif:
        yield None
        return

    tracer = trace.get_tracer("mardik")
    with tracer.start_as_current_span(nom) as courant:
        for cle, valeur in attributs.items():
            courant.set_attribute(cle, valeur)  # type: ignore[arg-type]
        yield courant
