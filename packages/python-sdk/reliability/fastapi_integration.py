"""
FastAPI Integration
"""

from fastapi import FastAPI, Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from typing import Callable, Type

from .client import ReliabilityClient


class FastAPIMiddleware(BaseHTTPMiddleware):
    """FastAPI middleware for error capture"""

    def __init__(self, app: FastAPI, client: ReliabilityClient):
        super().__init__(app)
        self.client = client

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        try:
            response = await call_next(request)
            return response
        except Exception as e:
            self.client.capture(e, request)
            raise


def setup_fastapi(app: FastAPI, client: ReliabilityClient):
    """Setup FastAPI integration"""
    app.add_middleware(FastAPIMiddleware, client=client)


def create_fastapi_middleware(client: ReliabilityClient) -> Type[FastAPIMiddleware]:
    """Create a configured FastAPI middleware class for manual use with add_middleware"""
    class _Configured(FastAPIMiddleware):
        def __init__(self, app: FastAPI):
            super().__init__(app, client)
    return _Configured
