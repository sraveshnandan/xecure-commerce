"""
Error Payload for Python SDK
"""

import hashlib
import platform
import os
import re
import traceback
from types import TracebackType
from typing import Any, Dict, Optional, TypedDict, Union
from datetime import datetime


class ServiceContext(TypedDict, total=False):
    pid: int
    runtime: str
    runtimeVersion: str
    pythonVersion: str
    platform: str
    hostname: str


class RequestContext(TypedDict, total=False):
    method: str
    url: str
    ip: str
    userAgent: str
    headers: Dict[str, Any]
    body: Any
    query: Any
    cookies: Any


class ErrorPayload(TypedDict, total=False):
    message: str
    name: str
    stack: str
    fingerprint: str
    timestamp: int
    service: str
    environment: str
    version: str
    release: str
    commitHash: str
    branch: str
    buildId: str
    deploymentId: str
    occurrenceCount: int
    severity: str
    errorType: str
    serviceContext: ServiceContext
    requestContext: RequestContext
    sdk_version: str


def _generate_fingerprint(error: Exception, stack: Optional[str] = None) -> str:
    signature = str(error)
    if stack:
        first_line = stack.split("\n")[0] if stack else ""
        signature += first_line
    return hashlib.sha256(signature.encode()).hexdigest()


_SENSITIVE_KEYS = {
    "authorization",
    "cookie",
    "set-cookie",
    "x-api-key",
    "api-key",
    "apikey",
    "password",
    "token",
    "access_token",
    "refresh_token",
    "secret",
    "signature",
}


def _sanitize_text(value: str) -> str:
    value = re.sub(r"Bearer\s+\S+", "Bearer [REDACTED]", value)
    for keyword in ("token", "password", "secret", "api_key", "apikey"):
        value = re.sub(rf"{re.escape(keyword)}=\S*", f"{keyword}=[REDACTED]", value)
    return value


def _sanitize_value(value: Any) -> Any:
    if isinstance(value, str):
        return _sanitize_text(value)
    if isinstance(value, dict):
        return {
            key: "[REDACTED]"
            if key.lower() in _SENSITIVE_KEYS
            or any(s in key.lower() for s in ("password", "secret", "token", "key", "auth", "cookie", "jwt", "bearer"))
            else _sanitize_value(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_sanitize_value(item) for item in value]
    return value


def _classify_error(error: Exception) -> str:
    msg = str(error).lower()
    if any(
        keyword in msg
        for keyword in ["database", "sql", "psycopg", "mysql", "sqlite"]
    ):
        return "DATABASE"
    if any(
        keyword in msg
        for keyword in ["network", "http", "socket", "connection", "timeout", "ssl"]
    ):
        return "NETWORK"
    if any(
        keyword in msg
        for keyword in ["validation", "invalid", "required", "constraint", "type"]
    ):
        return "VALIDATION"
    if any(
        keyword in msg
        for keyword in ["permission", "denied", "forbidden", "unauthorized"]
    ):
        return "AUTH"
    return "RUNTIME"


def _determine_severity(error: Exception) -> str:
    msg = str(error).lower()
    if any(
        keyword in msg
        for keyword in ["database", "connection", "timeout", "fatal", "crash"]
    ):
        return "critical"
    return "medium"


def _format_stack_trace(stack: Optional[Union[str, TracebackType]] = None) -> Optional[str]:
    if not stack:
        return None
    if isinstance(stack, str):
        return stack
    try:
        return "".join(traceback.format_tb(stack))
    except Exception:
        return None


def _build_service_context() -> ServiceContext:
    return {
        "pid": os.getpid(),
        "runtime": "python",
        "runtimeVersion": platform.python_version(),
        "pythonVersion": platform.python_version(),
        "platform": platform.platform(),
        "hostname": platform.node() or os.environ.get("HOSTNAME", "unknown"),
    }


def _extract_request_context(request: Optional[Any] = None) -> Optional[RequestContext]:
    if request is None:
        return None
    context: RequestContext = {}

    if hasattr(request, "method"):
        context["method"] = request.method
    if hasattr(request, "url"):
        context["url"] = str(request.url)
    if hasattr(request, "client") and request.client:
        context["ip"] = request.client.host
    if hasattr(request, "remote_addr"):
        context["ip"] = request.remote_addr
    if hasattr(request, "path"):
        context["url"] = context.get("url", request.path)
    if hasattr(request, "META"):
        context["ip"] = request.META.get("REMOTE_ADDR")
        context["method"] = request.method
        context["url"] = request.path
    if hasattr(request, "headers"):
        headers = dict(request.headers)
        forwarded = headers.get("x-forwarded-for")
        if forwarded and not context.get("ip"):
            context["ip"] = forwarded.split(",")[0].strip()
        user_agent = headers.get("user-agent")
        if user_agent:
            context["userAgent"] = user_agent
        context["headers"] = _sanitize_value(headers)

    body = request.json if hasattr(request, "json") and not callable(request.json) else None
    if body is not None:
        context["body"] = _sanitize_value(body)
    elif hasattr(request, "body") and not callable(request.body) and request.body is not None:
        context["body"] = _sanitize_value(request.body)

    if hasattr(request, "args") and request.args is not None:
        context["query"] = _sanitize_value(dict(request.args))
    if hasattr(request, "cookies") and request.cookies is not None:
        context["cookies"] = _sanitize_value(dict(request.cookies))
    return context if context else None


def create_error_payload(
    error: Exception,
    service_id: str,
    mode: str,
    request: Optional[Any] = None,
    *,
    version: Optional[str] = None,
    release: Optional[str] = None,
    commit_hash: Optional[str] = None,
    branch: Optional[str] = None,
    build_id: Optional[str] = None,
    deployment_id: Optional[str] = None,
) -> ErrorPayload:
    stack = getattr(error, "__fake_tb__", None) or _format_stack_trace(
        error.__traceback__
    )
    fingerprint = _generate_fingerprint(error, stack)
    return {
        "message": str(error),
        "name": type(error).__name__,
        "stack": stack or "",
        "fingerprint": fingerprint,
        "timestamp": int(datetime.now().timestamp() * 1000),
        "service": service_id,
        "environment": mode,
        **({"version": version} if version else {}),
        **({"release": release} if release else {}),
        **({"commitHash": commit_hash} if commit_hash else {}),
        **({"branch": branch} if branch else {}),
        **({"buildId": build_id} if build_id else {}),
        **({"deploymentId": deployment_id} if deployment_id else {}),
        "occurrenceCount": 1,
        "severity": _determine_severity(error),
        "errorType": _classify_error(error),
        "serviceContext": _build_service_context(),
        **(
            {"requestContext": request_context}
            if (request_context := _extract_request_context(request)) is not None
            else {}
        ),
    }
