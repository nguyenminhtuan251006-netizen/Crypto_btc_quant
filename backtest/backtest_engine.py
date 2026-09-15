"""
Backtest Engine with Institutional Cost & Slippage Modeling for Strategy 2
"""
import numpy as np
import pandas as pd

class Strategy2Backtester:
    def __init__(
        self,
        initial_capital: float = 6.0,
        leverage: float = 5.0,
        fee_rate: float = 0.00015,         # Default: Maker fee (0.015%)
        slippage_bps: float = 2.0,         # Default: 2 bps (0.02%)
        funding_rate_8h: float = 0.0001    # Typical Binance 0.01% / 8h
    ):
        self.initial_capital = initial_capital
        self.leverage = leverage
        self.fee_rate = fee_rate
        self.slippage_rate = slippage_bps / 10000.0
        self.funding_rate_bar = funding_rate_8h / 32.0 # 32 15m bars in 8 hours
        
    def run(self, df_test: pd.DataFrame, signals: np.ndarray, sl_prices: np.ndarray, tp_prices: np.ndarray, timeout_bars: int = 8) -> tuple[pd.DataFrame, pd.DataFrame]:
        df = df_test.copy().reset_index(drop=True)
        n = len(df)
        
        opens = df["open"].to_numpy()
        highs = df["high"].to_numpy()
        lows = df["low"].to_numpy()
        closes = df["close"].to_numpy()
        dts = df["datetime"].to_numpy()
        
        capital = self.initial_capital
        equity_curve = np.zeros(n)
        
        pos = 0 # 1: Long, -1: Short, 0: Flat
        entry_price = 0.0
        entry_time = None
        current_sl = 0.0
        current_tp = 0.0
        bars_held = 0
        trades = []
        
        for i in range(n - 1):
            equity_curve[i] = capital
            sig = signals[i]
            next_o = opens[i + 1]
            next_h = highs[i + 1]
            next_l = lows[i + 1]
            next_c = closes[i + 1]
            
            # 1. Manage active position
            if pos != 0:
                bars_held += 1
                exit_price = 0.0
                closed = False
                exit_reason = ""
                
                # Check execution on next bar
                if pos == 1:
                    # Long position
                    if next_l <= current_sl:
                        # Stop Loss hit
                        exit_price = current_sl * (1.0 - self.slippage_rate) # Slippage against us on stop
                        closed = True
                        exit_reason = "STOP_LOSS"
                    elif next_h >= current_tp:
                        # Take Profit hit (Limit Maker)
                        exit_price = current_tp
                        closed = True
                        exit_reason = "TAKE_PROFIT"
                elif pos == -1:
                    # Short position
                    if next_h >= current_sl:
                        exit_price = current_sl * (1.0 + self.slippage_rate)
                        closed = True
                        exit_reason = "STOP_LOSS"
                    elif next_l <= current_tp:
                        exit_price = current_tp
                        closed = True
                        exit_reason = "TAKE_PROFIT"
                        
                # Timeout exit after max bars
                if not closed and bars_held >= timeout_bars:
                    exit_price = next_c * (1.0 - self.slippage_rate if pos == 1 else 1.0 + self.slippage_rate)
                    closed = True
                    exit_reason = "TIMEOUT_2H"
                    
                if closed:
                    # Calculate return pct
                    gross_pnl_pct = (exit_price / entry_price - 1.0) if pos == 1 else (1.0 - exit_price / entry_price)
                    
                    # Position sizing with compounding
                    pos_val = max(5.0, capital * self.leverage)
                    
                    # Cost breakdown: Round-trip fees + Slippage + Funding
                    roundtrip_fee = pos_val * (self.fee_rate * 2)
                    funding_cost = pos_val * (self.funding_rate_bar * bars_held)
                    net_pnl = (pos_val * gross_pnl_pct) - roundtrip_fee - funding_cost
                    
                    capital += net_pnl
                    trades.append({
                        "entry_time": str(entry_time),
                        "exit_time": str(dts[i + 1]),
                        "direction": "LONG" if pos == 1 else "SHORT",
                        "entry_price": entry_price,
                        "exit_price": exit_price,
                        "pnl_pct": gross_pnl_pct * 100,
                        "net_pnl_usdt": net_pnl,
                        "capital_after": capital,
                        "bars_held": bars_held,
                        "reason": exit_reason
                    })
                    pos = 0
                    
            # 2. Open new position (on next bar open + slippage)
            if pos == 0 and sig != 0 and capital > 1.0:
                pos = sig
                # Entry slippage modeled realistically on Market fill
                entry_price = next_o * (1.0 + self.slippage_rate if pos == 1 else 1.0 - self.slippage_rate)
                entry_time = dts[i + 1]
                current_sl = sl_prices[i]
                current_tp = tp_prices[i]
                bars_held = 0
                
        equity_curve[-1] = capital
        df["equity"] = equity_curve
        trades_df = pd.DataFrame(trades)
        return df, trades_df

def compute_strategy2_metrics(df: pd.DataFrame, trades_df: pd.DataFrame, initial_capital: float) -> dict:
    final_capital = df["equity"].iloc[-1]
    total_ret = (final_capital / initial_capital - 1.0) * 100
    
    cummax = df["equity"].cummax()
    drawdown = (cummax - df["equity"]) / np.where(cummax == 0, 1.0, cummax) * 100
    max_dd = drawdown.max()
    
    if len(trades_df) == 0:
        return {
            "Final Capital": initial_capital,
            "Total Return (%)": 0.0,
            "Profit Factor": 0.0,
            "Sharpe Ratio": 0.0,
            "Win Rate (%)": 0.0,
            "Max Drawdown (%)": 0.0,
            "Total Trades": 0
        }
        
    wins = trades_df[trades_df["net_pnl_usdt"] > 0]
    losses = trades_df[trades_df["net_pnl_usdt"] <= 0]
    
    win_rate = len(wins) / len(trades_df) * 100
    gross_win = wins["net_pnl_usdt"].sum()
    gross_loss = abs(losses["net_pnl_usdt"].sum())
    profit_factor = (gross_win / (gross_loss + 1e-9)) if gross_loss > 0 else 999.0
    
    pnl_series = trades_df["net_pnl_usdt"]
    sharpe = (pnl_series.mean() / (pnl_series.std() + 1e-9)) * np.sqrt(96 * 30) # 96 15m bars/day
    
    return {
        "Initial Capital": round(initial_capital, 2),
        "Final Capital": round(final_capital, 2),
        "Total Return (%)": round(total_ret, 2),
        "Profit Factor": round(profit_factor, 2),
        "Sharpe Ratio": round(sharpe, 2),
        "Win Rate (%)": round(win_rate, 2),
        "Max Drawdown (%)": round(max_dd, 2),
        "Total Trades": len(trades_df),
        "Avg Win ($)": round(wins["net_pnl_usdt"].mean(), 2) if len(wins) else 0.0,
        "Avg Loss ($)": round(abs(losses["net_pnl_usdt"].mean()), 2) if len(losses) else 0.0
    }
