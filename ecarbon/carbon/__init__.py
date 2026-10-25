"""Stage 3 -- factor lookup, unit reconciliation, module-scope guard, totals."""

from ecarbon.carbon.calculate import calculate_carbon, compute_carbon_line, reconcile_units
from ecarbon.carbon.store import EC3Provider, FactorProvider, LocalSnapshotProvider

__all__ = [
    "calculate_carbon",
    "compute_carbon_line",
    "reconcile_units",
    "FactorProvider",
    "LocalSnapshotProvider",
    "EC3Provider",
]
