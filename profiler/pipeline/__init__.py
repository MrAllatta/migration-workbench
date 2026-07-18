"""Corpus pipeline abstraction package.

Provides the provider-agnostic :class:`CorpusPipeline` base class that
both Sheets and Coda adapters implement.
"""

from profiler.pipeline.base import CorpusPipeline


def get_dispatcher() -> "CorpusPipelineDispatcher":
    """Lazy import and return a new :class:`CorpusPipelineDispatcher`.

    Avoids circular-import cycles: adapters import from the legacy
    ``profiler.tools.*`` modules, which re-export from
    ``profiler.pipeline.selection``, which triggers a partial load
    of this package.  Deferring the dispatcher import breaks the cycle.
    """
    from profiler.pipeline.pipeline import CorpusPipelineDispatcher as _Dispatcher

    return _Dispatcher()


__all__ = ["CorpusPipeline", "get_dispatcher"]
