"""
AFCX Cross-Sectional Ranking & Gate Engine
===========================================
Implements Sections 11, 12, 13, 14, 15, 16, 17 of the AFCX Specification:
- Normalizes features cross-sectionally across the active universe.
- Computes Seed Direction Score (D_i) and Crowding Penalty (C_i).
- Ranks candidates by absolute score.
- Enforces Confidence Gate (|Score_1| >= 1.25, Gap >= 0.20).
- Enforces Direction Consensus Gate (>= 4 of 6 indicators agree).
- Enforces Cost Gate (Expected Move > 3 * Expected Cost).
"""
import numpy as np
import pandas as pd
from typing import List, Dict, Any, Tuple, Optional
from .flow_engine import winsorize_z


class CrossSectionalRanker:
    """Ranks candidate coins across liquid universe and applies strict quality gates."""

    def __init__(
        self,
        min_abs_score: float = 1.25,
        min_score_gap: float = 0.20,
        min_consensus: int = 4,
        cost_ratio_threshold: float = 3.0,
    ):
        self.min_abs_score = min_abs_score
        self.min_score_gap = min_score_gap
        self.min_consensus = min_consensus
        self.cost_ratio_threshold = cost_ratio_threshold

    def rank_universe(
        self,
        raw_features_list: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """
        Takes raw feature dictionaries from multiple symbols and performs
        cross-sectional Z-score normalization and ranking.
        """
        if not raw_features_list or len(raw_features_list) < 2:
            return []

        df = pd.DataFrame(raw_features_list)

        # Cross-sectional Z-score normalization for each metric (Section 8)
        norm_cols = ["m_1h", "m_4h", "ofi_15m", "oi_confirmation", "book_imbalance", "rel_volume", "funding_z", "basis_z"]
        for col in norm_cols:
            if col in df.columns:
                vals = df[col].to_numpy(dtype=float)
                mean = np.mean(vals)
                std = np.std(vals)
                if std > 1e-9:
                    z_series = (vals - mean) / std
                else:
                    z_series = vals - mean
                df[f"z_{col}"] = [winsorize_z(z, 3.0) for z in z_series]
            else:
                df[f"z_{col}"] = 0.0

        # Market-wide Network Momentum (mean momentum of the universe)
        net_momentum = float(df["z_m_1h"].mean())

        ranked_results = []
        for _, row in df.iterrows():
            sym = row["symbol"]

            # 1. Direction Score D_i (Section 11)
            # Weights: 0.20 M_1h + 0.15 M_4h + 0.25 OFI_15m + 0.15 OI + 0.10 Book + 0.10 Vol + 0.05 NetMom
            d_i = (
                0.20 * row["z_m_1h"]
                + 0.15 * row["z_m_4h"]
                + 0.25 * row["z_ofi_15m"]
                + 0.15 * row["z_oi_confirmation"]
                + 0.10 * row["z_book_imbalance"]
                + 0.10 * row["z_rel_volume"]
                + 0.05 * net_momentum
            )

            # 2. Crowding Penalty C_i (Section 12)
            c_i = 0.60 * row["z_funding_z"] + 0.40 * row["z_basis_z"]

            # Final Score with crowding reduction
            if d_i > 0:
                final_score = d_i - 0.20 * max(0.0, c_i)
            else:
                final_score = d_i + 0.20 * max(0.0, -c_i)

            # Direction consensus checks (Section 15)
            direction_sign = 1 if final_score > 0 else -1
            indicators = [
                row["z_m_1h"],
                row["z_ofi_15m"],
                row["z_oi_confirmation"],
                row["z_book_imbalance"],
                row["z_rel_volume"],
                row["z_m_4h"],
            ]
            agreement_count = sum(1 for ind in indicators if np.sign(ind) == direction_sign)

            ranked_results.append({
                "symbol": sym,
                "current_price": float(row["current_price"]),
                "atr_pct": float(row.get("atr_pct", 0.006)),
                "raw_direction": float(d_i),
                "crowding": float(c_i),
                "final_score": float(final_score),
                "abs_score": float(abs(final_score)),
                "direction": direction_sign,
                "consensus_count": int(agreement_count),
                "z_ofi": float(row["z_ofi_15m"]),
                "z_m1h": float(row["z_m_1h"]),
                "funding_raw": float(row.get("funding_raw", 0.0001)),
            })

        # Sort descending by absolute score
        ranked_results.sort(key=lambda x: x["abs_score"], reverse=True)
        return ranked_results

    def evaluate_top_candidate(
        self,
        ranked_list: List[Dict[str, Any]],
    ) -> Tuple[bool, Optional[Dict[str, Any]], str]:
        """
        Applies Confidence Gate, Consensus Gate, and Cost Gate to candidate #1.
        
        Returns:
            (qualified: bool, candidate: dict or None, reason: str)
        """
        if not ranked_list or len(ranked_list) < 2:
            return False, None, "Số lượng coin trong universe không đủ để xếp hạng"

        cand1 = ranked_list[0]
        cand2 = ranked_list[1]

        score1 = cand1["abs_score"]
        score2 = cand2["abs_score"]
        gap = score1 - score2

        # 1. Confidence Gate (Section 14)
        if score1 < self.min_abs_score:
            return False, None, f"Điểm cơ hội Top 1 ({cand1['symbol']} Score={cand1['final_score']:+.2f}) chưa đạt ngưỡng tối thiểu {self.min_abs_score}"

        if gap < self.min_score_gap:
            return False, None, f"Khoảng cách điểm số giữa Top 1 ({cand1['symbol']}: {score1:.2f}) và Top 2 ({cand2['symbol']}: {score2:.2f}) quá hẹp ({gap:.2f} < {self.min_score_gap})"

        # 2. Consensus Gate (Section 15)
        if cand1["consensus_count"] < self.min_consensus:
            return False, None, f"Độ đồng thuận chỉ báo của {cand1['symbol']} ({cand1['consensus_count']}/6) không đạt chuẩn tối thiểu {self.min_consensus}/6"

        # 3. Cost Gate (Section 17)
        # Expected Move = 1.8 * SL Distance
        atr_pct = max(cand1["atr_pct"] * 1.2, 0.0035)
        expected_move = 1.8 * atr_pct
        # Expected Cost = Taker Fee (0.05% * 2) + Slippage (0.04%) + Funding
        expected_cost = 0.0010 + 0.0004 + abs(cand1.get("funding_raw", 0.0001))
        if expected_cost > 0 and (expected_move / expected_cost) < self.cost_ratio_threshold:
            return False, None, f"Lợi thế kỳ vọng {expected_move*100:.2f}% chưa vượt trội 3x chi phí ước tính {expected_cost*100:.2f}%"

        dir_str = "LONG" if cand1["direction"] == 1 else "SHORT"
        reason = (
            f"✅ CHẤP THUẬN CƠ HỘI {dir_str} {cand1['symbol']} | "
            f"Score: {cand1['final_score']:+.2f} (Gap: +{gap:.2f}) | "
            f"Đồng thuận: {cand1['consensus_count']}/6 | "
            f"Biến động ATR: {cand1['atr_pct']*100:.2f}%"
        )
        return True, cand1, reason
