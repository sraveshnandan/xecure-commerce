"""
Django Integration
"""

import logging
import sys
from typing import Optional

from django.utils.deprecation import MiddlewareMixin

from .client import ReliabilityClient
from .config import ReliabilityConfig

logger = logging.getLogger(__name__)

_client: Optional[ReliabilityClient] = None


def get_client() -> Optional[ReliabilityClient]:
    """Get or create Django client"""
    global _client
    if _client is None:
        from django.conf import settings

        api_key = getattr(settings, "RELIABILITY_API_KEY", None)
        service_id = getattr(settings, "RELIABILITY_SERVICE_ID", None)
        mode = getattr(settings, "RELIABILITY_MODE", "development")

        if not api_key or not service_id:
            logger.warning(
                "Reliability SDK not configured. Add API_KEY and SERVICE_ID to settings."
            )
            return None

        config = ReliabilityConfig(api_key=api_key, service_id=service_id, mode=mode)
        _client = ReliabilityClient(config)

    return _client


class ReliabilityMiddleware(MiddlewareMixin):
    """Django middleware for error capture"""

    def process_exception(self, request, exception):
        """Capture exceptions"""
        client = get_client()
        if client:
            client.capture(exception, request)
        return None


# Django signals for automatic capture
def setup_django_signals():
    """Setup Django signals for automatic error capture"""
    try:
        from django.core.signals import got_request_exception
        from django.dispatch import receiver

        @receiver(got_request_exception)
        def capture_exception(sender, request=None, **kwargs):
            client = get_client()
            exception = sys.exc_info()[1]
            if client and exception:
                client.capture(exception, request)
    except ImportError:
        pass
