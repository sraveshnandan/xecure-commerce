"""
Flask Integration
"""

from flask import Flask, Response
from typing import Callable

from .client import ReliabilityClient


class FlaskMiddleware:
    """Flask middleware for error capture"""

    def __init__(self, app: Callable, client: ReliabilityClient):
        self.app = app
        self.client = client

    def __call__(self, environ: dict, start_response: Callable) -> Response:
        # Wrap start_response to capture exceptions
        def wrapped_start_response(status, headers, exc_info=None):
            return start_response(status, headers, exc_info)

        try:
            # Use Flask's internal mechanism
            from flask import g

            return self.app(environ, wrapped_start_response)
        except Exception as e:
            # Get request object from Flask
            from flask import request

            self.client.capture(e, request)
            raise


def init_flask(app: Flask, client: ReliabilityClient):
    """Initialize Flask integration"""

    @app.errorhandler(Exception)
    def handle_error(error):
        from flask import request

        client.capture(error, request)
        return {"error": "Internal server error"}, 500


def create_flask_error_handler(client: ReliabilityClient):
    """Create Flask error handler for manual use"""

    def handle_error(error):
        from flask import request

        client.capture(error, request)
        return {"error": "Internal server error"}, 500

    return handle_error
