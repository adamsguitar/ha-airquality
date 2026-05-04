"""Result type for managed Lovelace dashboard sync."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

DashboardSyncStatus = Literal["ok", "skipped", "failed"]


@dataclass(frozen=True)
class DashboardSyncResult:
    status: DashboardSyncStatus
    detail: str | None = None
