"""Langfuse tracing (AGENT-07): on only when both Langfuse keys are configured."""

import logging

from langchain_core.callbacks import BaseCallbackHandler

from spotwise.config import Settings

logger = logging.getLogger(__name__)


def tracing_callbacks(settings: Settings) -> list[BaseCallbackHandler]:
    """A Langfuse callback handler, or [] when tracing is off."""
    if settings.langfuse_public_key is None or settings.langfuse_secret_key is None:
        logger.info("Langfuse keys not set, tracing is off")
        return []
    # Imported here so the app works without Langfuse configured
    from langfuse import Langfuse
    from langfuse.langchain import CallbackHandler

    public_key = settings.langfuse_public_key.get_secret_value()
    # Creating the client registers it; the handler then finds it by public key
    Langfuse(
        public_key=public_key,
        secret_key=settings.langfuse_secret_key.get_secret_value(),
        host=settings.langfuse_host,
    )
    logger.info("Langfuse tracing on (%s)", settings.langfuse_host)
    return [CallbackHandler(public_key=public_key)]
