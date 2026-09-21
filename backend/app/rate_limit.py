"""
Minimal in-memory per-IP rate limiter for the upload endpoint. A single
process on a single small instance doesn't need a distributed limiter — a
plain sliding-window counter in memory is enough to stop one client from
hammering the VLM backend and is one less dependency to reason about.
"""
from __future__ import annotations

import time
from collections import defaultdict, deque

from fastapi import HTTPException, Request


class InMemoryRateLimiter:
    def __init__(self, max_requests: int, window_seconds: int = 60):
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    def check(self, key: str) -> None:
        now = time.monotonic()
        hits = self._hits[key]
        while hits and now - hits[0] > self.window_seconds:
            hits.popleft()
        if len(hits) >= self.max_requests:
            raise HTTPException(
                429, f"Rate limit exceeded: max {self.max_requests} requests per "
                     f"{self.window_seconds}s. Please wait and try again."
            )
        hits.append(now)


def client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"
