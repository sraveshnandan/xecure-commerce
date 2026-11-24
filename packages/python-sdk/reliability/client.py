"""
Reliability Client for Python SDK
"""

import asyncio
import json
import logging
import random
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, List, Optional
from urllib.request import Request, urlopen

from .config import RateLimitConfig, ReliabilityConfig
from .payload import create_error_payload

logger = logging.getLogger(__name__)

DEFAULT_ENDPOINT = "https://api.xecurecode.in/api/v1/ingest"
SDK_VERSION = "python@0.2.0"

DEDUP_WINDOW_MS = 60000
DEFAULT_MIN_INTERVAL_MS = 100
DEFAULT_MAX_PENDING = 100
DEFAULT_BATCH_SIZE = 10
DEFAULT_BATCH_FLUSH_MS = 5000


class ReliabilityClient:
    """Main reliability client for capturing and sending errors"""

    def __init__(self, config: ReliabilityConfig):
        self.config = config
        self._executor = ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="reliability-sender"
        )
        self._shutdown_flag = False

        # Rate limiting
        self._last_sent_time = 0
        self._pending_sends = 0
        self._lock = threading.Lock()

        # Batch queue
        self._batch_queue: List[Dict[str, Any]] = []
        self._batch_fingerprints: List[str] = []
        self._batch_flush_timer: Optional[threading.Timer] = None
        self._batch_size = DEFAULT_BATCH_SIZE
        self._batch_flush_ms = DEFAULT_BATCH_FLUSH_MS

        # Configurable rate limiting
        rate_limit = config.rate_limit or RateLimitConfig()
        self._min_interval_ms = rate_limit.min_interval_ms
        self._max_pending = rate_limit.max_pending

        # Sampling
        self._sample_rate = config.sample_rate

        # Debug mode
        self._debug = config.debug

        # Deduplication cache
        self._error_cache: Dict[str, float] = {}
        self._error_counts: Dict[str, int] = {}
        self._cache_cleanup_interval = 60
        self._cleanup_stop = threading.Event()
        self._cleanup_thread: Optional[threading.Thread] = None
        self._start_cache_cleanup()

        # Global exception handlers
        self._setup_global_handlers()

        if self._debug:
            logger.info(
                "ReliabilityClient initialized",
                extra={
                    "service_id": self.config.service_id,
                    "mode": self.config.mode,
                    "sample_rate": self._sample_rate,
                    "rate_limit": {
                        "min_interval_ms": self._min_interval_ms,
                        "max_pending": self._max_pending,
                    },
                },
            )

    def _setup_global_handlers(self):
        """Setup global exception handlers"""
        self._original_excepthook = sys.excepthook
        self._original_thread_excepthook = threading.excepthook

        sys.excepthook = self._custom_excepthook
        threading.excepthook = self._custom_thread_excepthook

    def _custom_excepthook(self, exc_type, exc_value, exc_traceback):
        """Custom uncaught exception handler"""
        try:
            if issubclass(exc_type, Exception):
                self.capture(exc_value)
        except Exception:
            pass
        if self._original_excepthook:
            self._original_excepthook(exc_type, exc_value, exc_traceback)

    def _custom_thread_excepthook(self, args):
        """Custom thread exception handler"""
        try:
            if args.exc_type and issubclass(args.exc_type, Exception):
                self.capture(args.exc_value)
        except Exception:
            pass
        if self._original_thread_excepthook:
            self._original_thread_excepthook(args)

    def _start_cache_cleanup(self):
        """Start background cache cleanup"""

        def cleanup():
            while not self._cleanup_stop.wait(self._cache_cleanup_interval):
                self._cleanup_cache()

        self._cleanup_thread = threading.Thread(
            target=cleanup,
            name="reliability-cache-cleanup",
            daemon=True,
        )
        self._cleanup_thread.start()

    def _cleanup_cache(self):
        """Remove old entries from cache"""
        now = time.time() * 1000
        expired_keys = [
            k for k, v in self._error_cache.items() if now - v > DEDUP_WINDOW_MS
        ]
        for k in expired_keys:
            self._error_cache.pop(k, None)
            self._error_counts.pop(k, None)

    def _record_fingerprint(self, fingerprint: str) -> int:
        """Record a fingerprint occurrence and return the accumulated count."""
        now = time.time() * 1000
        last_time = self._error_cache.get(fingerprint)
        current_count = self._error_counts.get(fingerprint, 0)

        if last_time is None:
            self._error_cache[fingerprint] = now
            self._error_counts[fingerprint] = 1
            return 1

        if now - last_time > DEDUP_WINDOW_MS:
            self._error_cache[fingerprint] = now
            self._error_counts[fingerprint] = 1
            return 1

        self._error_cache[fingerprint] = now
        current_count += 1
        self._error_counts[fingerprint] = current_count
        return current_count

    def _should_sample(self) -> bool:
        """Check if we should sample this error"""
        if self._sample_rate >= 1:
            return True
        if self._sample_rate <= 0:
            return False
        return random.random() < self._sample_rate

    def _can_send(self) -> bool:
        """Check if we can send (rate limiting)"""
        now = time.time() * 1000
        with self._lock:
            if now - self._last_sent_time < self._min_interval_ms:
                return False
            if self._pending_sends >= self._max_pending:
                return False
            return True

    def _log(self, message: str, **kwargs):
        """Log debug message if debug mode is enabled"""
        if self._debug:
            logger.debug(message, extra=kwargs)

    def _schedule_batch_flush(self):
        """Schedule batch flush"""
        if self._batch_flush_timer is not None:
            return
        self._batch_flush_timer = threading.Timer(
            self._batch_flush_ms / 1000, self._flush_batch_async
        )
        self._batch_flush_timer.daemon = True
        self._batch_flush_timer.start()

    def _flush_batch_async(self):
        """Flush batch asynchronously"""
        self._batch_flush_timer = None
        if self._batch_queue:
            self._executor.submit(self._flush_batch)

    def _flush_batch(self):
        """Flush batch queue to backend"""
        if not self._batch_queue:
            return

        batch = self._batch_queue[: self._batch_size]
        fingerprints = self._batch_fingerprints[: self._batch_size]
        self._batch_queue = self._batch_queue[self._batch_size :]
        self._batch_fingerprints = self._batch_fingerprints[self._batch_size :]

        with self._lock:
            self._pending_sends += 1
            self._last_sent_time = time.time() * 1000

        try:
            result = self._send_batch_to_backend(batch)
            if result.get("ok"):
                for fp in fingerprints:
                    self._consume_duplicate_count(fp)
                self._log("Batch sent successfully", count=len(batch))
            else:
                self._log("Batch send failed", status=result.get("status"), count=len(batch))
        except Exception as e:
            self._log("Batch send error", error=str(e), count=len(batch))
        finally:
            with self._lock:
                self._pending_sends -= 1
            if self._batch_queue:
                self._schedule_batch_flush()

    def _consume_duplicate_count(self, fingerprint: str) -> int:
        """Consume and reset duplicate count for a fingerprint"""
        entry_count = self._error_counts.get(fingerprint, 0)
        self._error_counts[fingerprint] = 0
        return entry_count

    def _add_sdk_version(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Add SDK version to payload"""
        return {**payload, "sdk_version": SDK_VERSION}

    def capture(self, error: Exception, request: Any = None):
        """Capture an error - never throws"""
        try:
            if error is None:
                return
            if self._shutdown_flag:
                self._log("Client shut down, dropping event")
                return

            if not self._should_sample():
                self._log("Dropped: sampling", sample_rate=self._sample_rate)
                return

            payload = create_error_payload(
                error,
                self.config.service_id,
                self.config.mode,
                request,
                version=self.config.version,
                release=self.config.release,
                commit_hash=self.config.commit_hash,
                branch=self.config.branch,
                build_id=self.config.build_id,
                deployment_id=self.config.deployment_id,
            )

            occurrence_count = self._record_fingerprint(payload["fingerprint"])

            if not self._can_send():
                self._log("Dropped: rate limited", pending_sends=self._pending_sends, max_pending=self._max_pending)
                return

            payload["occurrenceCount"] = occurrence_count
            payload = self._add_sdk_version(payload)

            self._log("Captured error", fingerprint=payload["fingerprint"], error_message=payload["message"])

            # Add to batch queue
            self._batch_queue.append(payload)
            self._batch_fingerprints.append(payload["fingerprint"])
            self._log("Queued for batch send", queue_length=len(self._batch_queue))

            if len(self._batch_queue) >= self._batch_size:
                self._executor.submit(self._flush_batch)
            else:
                self._schedule_batch_flush()

        except Exception as e:
            logger.exception(f"Reliability SDK internal error in capture(): {e}")

    def ingest_batch(self, errors: List[Exception], request: Any = None):
        """Capture multiple errors in a batch"""
        for error in errors:
            self.capture(error, request)

    def _send_to_backend(self, payload: Dict[str, Any]):
        """Send single payload to backend with retry"""
        max_retries = 3
        retry_delay = 1
        for attempt in range(max_retries):
            try:
                self._do_send(payload)
                self._log("Error sent successfully", error_message=payload["message"])
                break
            except Exception as e:
                self._log("Failed to send error", attempt=attempt + 1, error=str(e))
                if attempt < max_retries - 1:
                    time.sleep(retry_delay * (attempt + 1))
        with self._lock:
            self._pending_sends -= 1

    def _send_batch_to_backend(self, payloads: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Send batch payloads to backend"""
        endpoint = (self.config.endpoint or DEFAULT_ENDPOINT).replace("/ingest", "/ingest/batch")
        data = json.dumps(payloads).encode("utf-8")

        request = Request(
            endpoint,
            data=data,
            headers={
                "Content-Type": "application/json",
                "xc-api-key": self.config.api_key,
                "xc-service-id": self.config.service_id,
            },
            method="POST",
        )

        with urlopen(request, timeout=self.config.timeout / 1000) as response:
            if response.status >= 400:
                return {"ok": False, "status": response.status}
            return {"ok": True, "status": response.status}

    def _do_send(self, payload: Dict[str, Any]):
        """Perform actual HTTP request"""
        data = json.dumps(payload).encode("utf-8")
        endpoint = self.config.endpoint or DEFAULT_ENDPOINT

        request = Request(
            endpoint,
            data=data,
            headers={
                "Content-Type": "application/json",
                "xc-api-key": self.config.api_key,
                "xc-service-id": self.config.service_id,
            },
            method="POST",
        )

        with urlopen(request, timeout=self.config.timeout / 1000) as response:
            if response.status >= 400:
                raise Exception(f"HTTP {response.status}")

    def middleware(self):
        """Create middleware for frameworks"""
        return ReliabilityMiddleware(self)

    def flush(self, timeout: float = 5.0):
        """Synchronously flush pending batch queue and wait for delivery"""
        if self._batch_flush_timer:
            self._batch_flush_timer.cancel()
            self._batch_flush_timer = None
        while self._batch_queue:
            self._flush_batch()
        start = time.time()
        while self._pending_sends > 0 and (time.time() - start) < timeout:
            time.sleep(0.05)

    async def flush_async(self, timeout: float = 5.0):
        """Asynchronously flush pending batch queue and wait for delivery"""
        self.flush(timeout=timeout)

    def shutdown(self):
        """Shutdown the client"""
        self._shutdown_flag = True
        if getattr(self, "_original_excepthook", None):
            sys.excepthook = self._original_excepthook
        if getattr(self, "_original_thread_excepthook", None):
            threading.excepthook = self._original_thread_excepthook
        self._cleanup_stop.set()
        if self._batch_flush_timer:
            self._batch_flush_timer.cancel()
            self._batch_flush_timer = None
        while self._batch_queue:
            self._flush_batch()
        self._executor.shutdown(wait=True)


class ReliabilityMiddleware:
    """Middleware for FastAPI/Flask"""

    def __init__(self, client: ReliabilityClient):
        self.client = client

    async def __call__(self, request, call_next):
        """Process request"""
        try:
            response = await call_next(request)
            return response
        except Exception as e:
            self.client.capture(e, request)
            raise


def get_client() -> ReliabilityClient:
    """Get global client instance"""
    if not hasattr(get_client, "_instance"):
        raise RuntimeError("ReliabilityClient not initialized. Call init() first.")
    return get_client._instance


def init(config: ReliabilityConfig) -> ReliabilityClient:
    """Initialize global client"""
    get_client._instance = ReliabilityClient(config)
    return get_client._instance


def lambda_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """AWS Lambda handler wrapper"""
    # This is a helper to capture Lambda errors
    # Usage: wrap your handler with @reliability.lambda_handler
    def decorator(func):
        def wrapper(*args, **kwargs):
            client = get_client()
            try:
                return func(*args, **kwargs)
            except Exception as e:
                client.capture(e, event)
                raise
        return wrapper
    return decorator