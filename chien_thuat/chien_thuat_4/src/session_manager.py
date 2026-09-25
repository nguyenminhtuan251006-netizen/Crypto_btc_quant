"""
AFCX Session Profile & Persistence Gate Manager
================================================
Implements AFCX v3 Dual-Session Architecture (Sections 2, 4, 5):
1. AFCX-LIQUID: 15:00 -> 04:00 VN Time (08:00 -> 21:00 UTC)
2. AFCX-ASIA:   04:00 -> 15:00 VN Time (21:00 -> 08:00 UTC)
3. Persistence Gate for AFCX-ASIA: Top 1 must maintain symbol & direction
   across >= 2 consecutive scans before entry is permitted.
"""
from dataclasses import dataclass
from datetime import datetime, time, timezone, timedelta
from typing import Optional, Tuple


@dataclass
class SessionProfileConfig:
    """Configuration for a single session profile."""
    name: str                       # "LIQUID" or "ASIA"
    trend_z_min: float             # Min |Z| score in TREND regime
    range_z_min: float             # Min |Z| score in RANGE regime
    confidence_gap_min: float      # Min score gap between Top 1 and Top 2
    consensus_min: int             # Min indicator agreement count out of 6
    cost_multiple_min: float       # Min expected edge to total cost ratio
    max_spread_pct: float          # Max allowed spread for entry (Review Issue 3)
    persistence_required: bool     # True for ASIA, False for LIQUID
    required_consecutive_ranks: int = 2
    client_order_prefix: str = "AFCX-LIQ"


# --- Profile Definitions (Spec Section 4) ---

LIQUID_PROFILE = SessionProfileConfig(
    name="LIQUID",
    trend_z_min=1.50,               # Raised from 1.25 -> 1.50 for high-conviction entries
    range_z_min=1.55,               # Strategies 4/5: relaxed from 1.65 for LIQUID RANGE/TRANSITION
    confidence_gap_min=0.30,        # Raised from 0.20 -> 0.30 (Top 1 must dominate)
    consensus_min=4,
    cost_multiple_min=2.5,
    max_spread_pct=0.0005,          # 0.05% — tight spread for high-liquidity session
    persistence_required=False,
    required_consecutive_ranks=1,
    client_order_prefix="AFCX-LIQ",
)

ASIA_PROFILE = SessionProfileConfig(
    name="ASIA",
    trend_z_min=1.60,               # Raised from 1.40 -> 1.60 for extra safety in thin session
    range_z_min=1.75,               # Raised from 1.55 -> 1.75
    confidence_gap_min=0.35,        # Raised from 0.30 -> 0.35
    consensus_min=5,
    cost_multiple_min=3.0,
    max_spread_pct=0.0008,          # 0.08% — wider spread tolerance for thin Asian session
    persistence_required=True,
    required_consecutive_ranks=2,
    client_order_prefix="AFCX-ASI",
)


class SessionManager:
    """Manages active session detection and persistence validation for AFCX."""

    def __init__(self):
        # Persistence Gate state for ASIA session
        self.last_candidate_symbol: Optional[str] = None
        self.last_candidate_direction: Optional[int] = None
        self.consecutive_candidate_hits: int = 0
        self.last_candidate_timestamp: float = 0.0
        # Track previous session for boundary detection (Review Issue 1)
        self._previous_session_name: Optional[str] = None

    @staticmethod
    def get_vietnam_time(dt: Optional[datetime] = None) -> datetime:
        """Get current Vietnam local time (UTC+7)."""
        if dt is None:
            dt = datetime.now(timezone.utc)
        elif dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        vn_tz = timezone(timedelta(hours=7))
        return dt.astimezone(vn_tz)

    @classmethod
    def resolve_session(cls, dt: Optional[datetime] = None) -> SessionProfileConfig:
        """
        Determines active profile according to Vietnam time (Spec Section 2):
        - ASIA:   04:00:00 <= VN_TIME < 15:00:00
        - LIQUID: VN_TIME >= 15:00:00 or VN_TIME < 04:00:00
        """
        vn_dt = cls.get_vietnam_time(dt)
        cur_time = vn_dt.time()

        if time(4, 0, 0) <= cur_time < time(15, 0, 0):
            return ASIA_PROFILE
        return LIQUID_PROFILE

    def detect_session_boundary_crossed(self) -> bool:
        """
        Returns True if the session profile has changed since last check (Review Issue 1).
        Used to trigger consecutive_losses reset at session boundaries.
        """
        current = self.resolve_session()
        crossed = (
            self._previous_session_name is not None
            and self._previous_session_name != current.name
        )
        self._previous_session_name = current.name
        return crossed

    def check_persistence_gate(
        self,
        candidate_symbol: str,
        candidate_direction: int,
        now_ts: float,
        profile: SessionProfileConfig,
    ) -> Tuple[bool, str]:
        """
        Spec Section 5: Persistence Gate for Asian session.
        Candidate must hold the exact same symbol and direction across
        >= 2 consecutive scans. Max 300 seconds between consecutive scans.
        """
        if not profile.persistence_required:
            return True, "Persistence Gate: Bỏ qua (Phiên LIQUID)"

        if now_ts == self.last_candidate_timestamp:
            return False, "PERSISTENCE: Chờ bảng xếp hạng mới, không đếm lại dữ liệu cache"

        is_same_candidate = (
            self.last_candidate_symbol == candidate_symbol
            and self.last_candidate_direction == candidate_direction
            and (now_ts - self.last_candidate_timestamp) <= 300.0
        )

        if is_same_candidate:
            self.consecutive_candidate_hits += 1
        else:
            self.last_candidate_symbol = candidate_symbol
            self.last_candidate_direction = candidate_direction
            self.consecutive_candidate_hits = 1

        self.last_candidate_timestamp = now_ts

        needed = profile.required_consecutive_ranks
        cur = self.consecutive_candidate_hits

        if cur >= needed:
            return True, f"✅ PERSISTENCE PASS: {candidate_symbol} duy trì Top 1 liên tục {cur} lượt"
        else:
            return False, f"⏳ PERSISTENCE CHỜ ({cur}/{needed}): {candidate_symbol} cần thêm {needed - cur} lượt quét"

    def reset_persistence(self):
        """Reset persistence counter upon trade execution or error."""
        self.last_candidate_symbol = None
        self.last_candidate_direction = None
        self.consecutive_candidate_hits = 0
        self.last_candidate_timestamp = 0.0
