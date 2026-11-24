"""
Reliability Config for Python SDK
"""

from dataclasses import dataclass
from typing import Literal, Optional

Mode = Literal["development", "production"]


@dataclass
class RateLimitConfig:
    min_interval_ms: int = 100
    max_pending: int = 100


@dataclass
class ReliabilityConfig:
    api_key: str
    service_id: str
    mode: Mode = "development"
    timeout: int = 5000
    endpoint: Optional[str] = None
    version: Optional[str] = None
    release: Optional[str] = None
    commit_hash: Optional[str] = None
    branch: Optional[str] = None
    build_id: Optional[str] = None
    deployment_id: Optional[str] = None
    sample_rate: float = 1.0
    rate_limit: Optional[RateLimitConfig] = None
    debug: bool = False

    def __post_init__(self):
        if not self.api_key:
            raise ValueError("API Key is required")
        if not self.service_id:
            raise ValueError("Service ID is required")
        if self.mode not in ["development", "production"]:
            raise ValueError("Mode must be 'development' or 'production'")
        if self.timeout <= 0:
            raise ValueError("Timeout must be greater than 0")
        if not 0 <= self.sample_rate <= 1:
            raise ValueError("sample_rate must be between 0 and 1")
