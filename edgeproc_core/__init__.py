"""edgeproc-core — vector partitioning and generic partition-key management.

The bottom layer of the edge-reco / edge-proc stack. Two independent modules:

- :mod:`edgeproc_core.vector_mgmt` — route embeddings into partitions and merge
  top-k results back out, over any search backend that satisfies the
  ``VectorIndex`` protocol.
- :mod:`edgeproc_core.errors` — canonical error codes: classify raw failures
  into stable codes, describe them, serialize to RFC 9457 Problem Details.

Homepage: https://github.com/hseshadr/edgeproc-core
"""

from importlib.metadata import PackageNotFoundError, version

# Re-export vector_mgmt for backward compatibility and convenience
# Package exports
from edgeproc_core import vector_mgmt
from edgeproc_core.vector_mgmt import (
    BucketedPartitionStrategy,
    GlobalPartitionStrategy,
    IndexConfig,
    IndexManager,
    IndexStats,
    PartitionStrategy,
    TwoTierPartitionStrategy,
    VectorEmbedding,
    VectorIndex,
)

# Derived from the installed distribution metadata so it can never drift from
# pyproject.toml (the publish `sed` bumps only pyproject). Single source of truth.
try:
    __version__ = version("edgeproc-core")
except PackageNotFoundError:  # pragma: no cover - source checkout, not installed
    __version__ = "0.0.0+unknown"

__all__ = [
    "BucketedPartitionStrategy",
    "GlobalPartitionStrategy",
    "IndexConfig",
    "IndexManager",
    "IndexStats",
    "PartitionStrategy",
    "TwoTierPartitionStrategy",
    "VectorEmbedding",
    "VectorIndex",
    "vector_mgmt",
]
