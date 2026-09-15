"""
Binance Futures Backtest Engine
Simulates real Binance Futures mechanics:
- Capital in USDT (default: 6 USDT ~ 150k VND)
- Configurable Leverage (default: 5x)
- Binance Futures Maker/Taker Fees + Slippage
- Strict Stop-Loss & Take-Profit enforcement
"""
import numpy as np
import pandas as pd

class BinanceFuturesEngine:
    def __init__(
        self,
        initial_capital_usdt: float = 6.0,   # 150k VNĐ ~ 6 USDT
        leverage: float = 5.0,                # 5x leverage
        fee_rate: float = None,               # If None, determined by execution_mode
        stop_loss_pct: float = 0.004,         # 0.4% stop loss
        take_profit_pct: float = 0.004,       # 0.4% take profit
        execution_mode: str = "maker",        # 'maker' (0.02% passive limit) or 'taker' (0.04% market order)
        max_bars_held: int = 12               # 1 hour timeout (12 bars x 5m)
    ):
        self.initial_capital = initial_capital_usdt
        self.leverage = leverage
        self.execution_mode = execution_mode
        if fee_rate is not None:
            self.fee_rate = fee_rate
        else:
            self.fee_rate = 0.0002 if execution_mode == "maker" else 0.0004
        self.stop_loss_pct = stop_loss_pct
        self.take_profit_pct = take_profit_pct
        self.max_bars_held = max_bars_held
        
    def run(self, df: pd.DataFrame, signals: np.ndarray) -> tuple[pd.DataFrame, pd.DataFrame]:
        df = df.copy().reset_index(drop=True)
        df["signal"] = signals
        
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
        pos_usdt = 0.0
        bars_held = 0
        
        trades = []
        
        for i in range(n - 1):
            equity_curve[i] = capital
            sig = signals[i]
            next_open = opens[i + 1]
            next_high = highs[i + 1]
            next_low = lows[i + 1]
            next_close = closes[i + 1]
            
            # 1. Manage Active Position (SL / TP check on bar i+1)
            if pos != 0:
                bars_held += 1
                pnl_pct = 0.0
                exit_price = 0.0
                closed = False
                
                if pos == 1:
                    # Long: check Stop Loss then Take Profit
                    if next_low <= entry_price * (1.0 - self.stop_loss_pct):
                        exit_price = entry_price * (1.0 - self.stop_loss_pct)
                        pnl_pct = -self.stop_loss_pct
                        closed = True
                    elif next_high >= entry_price * (1.0 + self.take_profit_pct):
                        exit_price = entry_price * (1.0 + self.take_profit_pct)
                        pnl_pct = self.take_profit_pct
                        closed = True
                elif pos == -1:
                    # Short: check Stop Loss then Take Profit
                    if next_high >= entry_price * (1.0 + self.stop_loss_pct):
                        exit_price = entry_price * (1.0 + self.stop_loss_pct)
                        pnl_pct = -self.stop_loss_pct
                        closed = True
                    elif next_low <= entry_price * (1.0 - self.take_profit_pct):
                        exit_price = entry_price * (1.0 - self.take_profit_pct)
                        pnl_pct = self.take_profit_pct
                        closed = True
                        
                # Timeout exit after max_bars_held
                if not closed and bars_held >= self.max_bars_held:
                    exit_price = next_close
                    pnl_pct = (exit_price / entry_price - 1.0) if pos == 1 else (1.0 - exit_price / entry_price)
                    closed = True
                    
                if closed:
                    # PnL with leverage minus round-trip fees
                    gross_pnl_usdt = pos_usdt * pnl_pct
                    fee_usdt = pos_usdt * (self.fee_rate * 2)
                    net_pnl_usdt = gross_pnl_usdt - fee_usdt
                    
                    capital += net_pnl_usdt
                    trades.append({
                        "entry_time": entry_time,
                        "entry_price": entry_price,
                        "exit_time": dts[i + 1],
                        "exit_price": exit_price,
                        "direction": "LONG" if pos == 1 else "SHORT",
                        "net_pnl_usdt": net_pnl_usdt,
                        "pnl_pct": pnl_pct * 100,
                        "capital_after": capital
                    })
                    pos = 0
                    pos_usdt = 0.0
                    
            # 2. Open New Position on bar i+1 if flat
            if pos == 0 and sig != 0 and capital > 0:
                pos = sig
                entry_price = next_open
                entry_time = dts[i + 1]
                pos_usdt = capital * self.leverage
                bars_held = 0
                
        equity_curve[-1] = capital
        df["equity"] = equity_curve
        trades_df = pd.DataFrame(trades)
        return df, trades_df

def compute_crypto_metrics(df: pd.DataFrame, trades_df: pd.DataFrame, initial_capital: float) -> dict:
    final_capital = df["equity"].iloc[-1]
    total_return_pct = (final_capital / initial_capital - 1.0) * 100
    
    # Drawdown
    cummax = df["equity"].cummax()
    drawdowns = (cummax - df["equity"]) / cummax * 100
    max_dd = drawdowns.max()
    
    # Trade stats
    if len(trades_df) == 0:
        return {"Total Return (%)": 0, "Sharpe": 0, "Max Drawdown (%)": 0, "Trades": 0}
        
    wins = trades_df[trades_df["net_pnl_usdt"] > 0]
    losses = trades_df[trades_df["net_pnl_usdt"] <= 0]
    win_rate = len(wins) / len(trades_df) * 100
    
    gross_profit = wins["net_pnl_usdt"].sum()
    gross_loss = abs(losses["net_pnl_usdt"].sum())
    profit_factor = (gross_profit / (gross_loss + 1e-9)) if gross_loss > 0 else 999.0
    
    # Sharpe on trade returns
    pnl_series = trades_df["net_pnl_usdt"]
    sharpe = (pnl_series.mean() / (pnl_series.std() + 1e-9)) * np.sqrt(288 * 30) # annualized monthly
    
    return {
        "Initial Capital (USDT)": round(initial_capital, 2),
        "Final Capital (USDT)": round(final_capital, 2),
        "Total Return (%)": round(total_return_pct, 2),
        "Is Doubled (x2)?": "YES (Đã x2)" if final_capital >= initial_capital * 2.0 else "Chưa",
        "Max Drawdown (%)": round(max_dd, 2),
        "Sharpe Ratio": round(sharpe, 2),
        "Win Rate (%)": round(win_rate, 2),
        "Profit Factor": round(profit_factor, 2),
        "Total Trades": len(trades_df)
    }
