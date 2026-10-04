"""Pace NVIDIA NIM traffic to its free-tier RPM inside a rolling 60s window.

NIM's free tier allows 40 requests/minute and answers the 41st with 429. The
deployment-level `rpm:` in litellm.config.yaml does not cover the path Claude
Code actually uses: it calls /v1/messages, which routes through
`anthropic_response` -> `base_process_llm_request`, and the 429s we were taking
came back from integrate.api.nvidia.com itself rather than from the router's
limiter. Setting `rpm` lower did nothing because that limiter was never in the
request path.

`pre_call_hook` IS awaited on that path (proxy/common_request_processing.py),
so waiting here holds request 41 until the oldest of the previous 40 ages out
of the window. The caller gets a slow 200 instead of a fast 429, which is what
makes CLAUDE_CODE_MAX_RETRIES stop being load-bearing: a retry ladder recovers
from rate limiting, it does not avoid it, and every retry burns a slot in the
same window that rejected it.

Only NIM is paced. Ollama, OpenRouter and Anthropic traffic pass straight
through, so this costs nothing when NIM is not the selected provider.
"""
from __future__ import annotations

import asyncio
import logging
import os
import time
from collections import deque

from litellm.integrations.custom_logger import CustomLogger

WINDOW_SECONDS = 60.0
log = logging.getLogger("nim_pacer")


class NimRpmPacer(CustomLogger):
    """Sliding-window admission control, blocking rather than rejecting.

    A sliding log rather than a fixed bucket: a fixed window lets 2x the limit
    through across a boundary (40 at 0:59, 40 at 1:01), which is the case NIM
    actually rejects.
    """

    def __init__(
        self,
        limit: int | None = None,
        window: float = WINDOW_SECONDS,
        match: str | None = None,
    ) -> None:
        self.limit = limit if limit is not None else int(os.environ.get("NIM_RPM", "40"))
        self.window = window
        self.match = (match or os.environ.get("NIM_RPM_MODEL_MATCH", "nim")).lower()
        # A window counter alone still lets all `limit` requests leave in the
        # same instant, which is the shape a provider rejects first. Spacing
        # them window/limit apart spends the same budget as a smooth stream.
        self._min_gap = self.window / max(self.limit, 1)
        self._hits: deque[float] = deque()
        self._lock = asyncio.Lock()
        log.warning(
            "nim pacer armed: %s req / %.0fs, matching model ~%r",
            self.limit,
            self.window,
            self.match,
        )

    async def async_pre_call_hook(self, user_api_key_dict, cache, data, call_type):
        if self.match not in str(data.get("model", "")).lower():
            return data

        # ponytail: the lock is held across the sleep deliberately - admission
        # is FIFO and request 41 does not race 42 for the slot that just freed.
        # Swap for a semaphore + per-slot timing if ordering ever stops mattering
        # and the serialisation shows up in latency.
        async with self._lock:
            while True:
                now = time.monotonic()
                cutoff = now - self.window
                while self._hits and self._hits[0] <= cutoff:
                    self._hits.popleft()
                if self._hits:
                    gap = now - self._hits[-1]
                    if gap < self._min_gap:
                        await asyncio.sleep(self._min_gap - gap)
                        continue
                if len(self._hits) < self.limit:
                    self._hits.append(now)
                    log.debug("nim pacer: admit (%s/%s in window)", len(self._hits), self.limit)
                    return data
                # Oldest hit leaves the window at _hits[0] + window; it is still
                # inside it here, so this is always > 0.
                wait = self._hits[0] - cutoff
                log.warning("nim pacer: window full (%s), holding %.1fs", self.limit, wait)
                await asyncio.sleep(wait)


# ponytail: LiteLLM's own internal retries re-hit NIM without re-entering this
# hook, so they are not counted. Lower NIM_RPM if edge 429s survive the pacer.
instance = NimRpmPacer()


if __name__ == "__main__":  # self-check: python nim_pacer.py

    async def _check() -> None:
        pacer = NimRpmPacer(limit=4, window=1.0)  # min gap 0.25s
        nim = {"model": "claude-oss-nim"}

        start = time.monotonic()
        for _ in range(4):
            await pacer.async_pre_call_hook(None, None, nim, "acompletion")
        spread = time.monotonic() - start
        assert 0.6 < spread < 0.95, f"4 admits should be ~0.25s apart, took {spread:.2f}s"

        await pacer.async_pre_call_hook(None, None, nim, "acompletion")
        waited = time.monotonic() - start
        assert waited >= 1.0, f"5th must wait for the window to free, waited {waited:.2f}s"

        other = {"model": "claude-oss-ollama"}
        start = time.monotonic()
        for _ in range(50):
            await pacer.async_pre_call_hook(None, None, other, "acompletion")
        assert time.monotonic() - start < 0.1, "non-NIM traffic must never be paced"

        print("nim_pacer self-check ok")

    asyncio.run(_check())
