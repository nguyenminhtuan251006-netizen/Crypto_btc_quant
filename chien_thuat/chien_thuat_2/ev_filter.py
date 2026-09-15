"""
Expected Value & Volatility Filter for Strategy 2
"""
import numpy as np

def compute_expected_value(prob_win: float, tp_r: float = 1.8, sl_r: float = 1.0, cost_r: float = 0.08) -> float:
    """
    EV = p * (1.8R - C) - (1 - p) * (1.0R + C)
    """
    ev = prob_win * (tp_r - cost_r) - (1.0 - prob_win) * (sl_r + cost_r)
    return ev

def evaluate_setup_ev(prob_win: float, atr_val: float, atr_pct_rank: float, config) -> tuple[bool, float, str]:
    """
    Evaluates whether candidate setup should be TAKEN or SKIPPED.
    Returns: (is_approved, ev_value, reason)
    """
    # 1. Volatility Regime Filter (Section 20)
    if atr_pct_rank < config.atr_pct_min:
        return False, 0.0, f"SKIP: Volatility too low (ATR rank {atr_pct_rank:.1f}% < {config.atr_pct_min}%)"
    if atr_pct_rank > config.atr_pct_max:
        return False, 0.0, f"SKIP: Wild volatility spike (ATR rank {atr_pct_rank:.1f}% > {config.atr_pct_max}%)"
        
    # 2. EV Calculation
    ev = compute_expected_value(prob_win, tp_r=config.tp_atr_mult, sl_r=config.sl_atr_mult, cost_r=config.est_cost_r)
    
    # 3. Decision
    if ev >= config.ev_minimum:
        return True, ev, f"TAKE: EV {ev:+.2f}R >= {config.ev_minimum}R (WinProb {prob_win*100:.1f}%)"
    else:
        return False, ev, f"SKIP: Insufficient EV ({ev:+.2f}R < {config.ev_minimum}R)"
