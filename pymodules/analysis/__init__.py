"""Post-simulation batch metrics for spoofing-aware vs baseline runs."""

from __future__ import annotations

from typing import Any

__all__ = [
    "load_sca_scalars",
    "summarize_sweep_directory",
]


def __getattr__(name: str) -> Any:
    """Lazy imports so ``python -m pymodules.analysis.spoofing_batch_metrics`` works."""
    if name == "load_sca_scalars":
        from pymodules.analysis.spoofing_batch_metrics import load_sca_scalars

        return load_sca_scalars
    if name == "summarize_sweep_directory":
        from pymodules.analysis.spoofing_batch_metrics import summarize_sweep_directory

        return summarize_sweep_directory
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
