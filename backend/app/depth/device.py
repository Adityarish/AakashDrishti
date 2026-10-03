"""VRAM-aware model lifecycle helpers.

CLAUDE.md hard constraint: the dev target is an 8GB-class GPU, so the two
depth backbones must never be resident on the GPU at the same time. Each
adapter loads its model inside `cuda_scope`, runs inference, and the model is
unloaded and CUDA cache cleared before the next adapter loads.
"""

from __future__ import annotations

import gc
from contextlib import contextmanager
from typing import Iterator

import torch

from app.core.logging import get_logger

logger = get_logger(__name__)


@contextmanager
def cuda_scope(label: str) -> Iterator[None]:
    """Log VRAM usage around a block and clear CUDA cache on exit."""
    try:
        yield
    finally:
        gc.collect()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
            allocated = torch.cuda.memory_allocated() / 1024**2
            reserved = torch.cuda.memory_reserved() / 1024**2
            logger.info(
                "[%s] VRAM after cleanup: allocated=%.1fMB reserved=%.1fMB",
                label,
                allocated,
                reserved,
            )


def resolve_device(preferred: str) -> torch.device:
    if preferred == "cuda" and not torch.cuda.is_available():
        logger.warning("CUDA requested but not available; falling back to CPU")
        return torch.device("cpu")
    return torch.device(preferred)
