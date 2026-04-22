"""Forget policy configuration."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ForgetPolicy:
    """Forget policy configuration - multi-dimensional scoring weights."""

    # Dimension weights
    access_weight: float = 0.25      # Access frequency weight
    age_weight: float = 0.20         # Age/time decay weight
    redundancy_weight: float = 0.25  # Redundancy (neighbor similarity) weight
    density_weight: float = 0.15     # Information density weight
    source_weight: float = 0.15      # Source type weight

    # Thresholds
    forget_threshold: float = 0.70   # Consider forgetting when score > this
    delete_threshold: float = 0.85   # Direct delete when score > this
    archive_threshold: float = 0.75  # Archive when score > this

    # Time baselines
    max_age_days: float = 30.0       # Age normalization baseline
    recent_protection_days: int = 3  # New memory protection period

    # Cycle interval
    cycle_interval_hours: int = 24   # Forget cycle interval


@dataclass
class ForgetReport:
    """Report from a forget cycle execution."""

    deleted: list[str] = field(default_factory=list)   # Deleted shard IDs
    archived: list[str] = field(default_factory=list)  # Archived shard IDs
    kept: list[str] = field(default_factory=list)      # Kept shard IDs
    threshold: float = 0.0                             # Threshold used
    executed_at: float = 0.0                           # Execution timestamp