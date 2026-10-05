"""Ask a typed question through the provider configured in Settings.

`cbc.shared.ai` does the asking; this resolves which provider answers (read per
call, so a change on the settings screen takes effect on the next question) and
keeps answers in `aiAnswers`, so a re-run of the same page or the same candidate
list costs nothing and answers the same way.
"""
from __future__ import annotations

import asyncio
from collections.abc import Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import TypeVar

from pydantic import BaseModel

from cbc.modules.ops.api import claude_cli, provider
from cbc.modules.ops.api.worker import claude_config
from cbc.modules.ops.infrastructure.collections import ai_answers
from cbc.shared import ai

T = TypeVar("T", bound=BaseModel)

# ponytail: one process-wide limit; per-provider limits if one provider throttles harder.
_CONCURRENCY = asyncio.Semaphore(4)


async def transport() -> ai.Transport:
    config = await claude_config()
    env, _sources = provider.build_env(config)
    mode = provider.resolve_mode(config)
    if mode == provider.ANTHROPIC_API and env.get("ANTHROPIC_API_KEY"):
        return ai.api_transport(env)
    return ai.cli_transport(env, claude_bin=claude_cli.resolve_binary())


async def ask(question: ai.Question[T], prompt: str, *, images: Sequence[Path] = ()) -> ai.Asked[T]:
    key = ai.cache_key(question, prompt, images)
    cache: dict[str, dict] = {}
    stored = await ai_answers().find_one({"_id": key})
    if stored:
        cache[key] = stored["answer"]
    send = await transport()
    async with _CONCURRENCY:
        asked = await asyncio.to_thread(ai.ask, question, prompt, transport=send, images=images, cache=cache)
    if asked.answer is not None and not asked.cached:
        await ai_answers().replace_one(
            {"_id": key},
            {"_id": key, "question": question.name, "version": question.version,
             "answer": cache[key], "at": datetime.now(timezone.utc)},
            upsert=True,
        )
    return asked
