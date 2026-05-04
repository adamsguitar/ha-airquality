"""Result type for managed Lovelace dashboard sync."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

DashboardSyncStatus = Literal["ok", "skipped", "failed"]
DashboardSkipReason = Literal[
    "none",
    "lovelace_unavailable",
    "coordinator_not_ready",
    "sidebar_path_blocked",
]


@dataclass(frozen=True)
class DashboardSyncResult:
    status: DashboardSyncStatus
    detail: str | None = None
    skip_reason: DashboardSkipReason = "none"
