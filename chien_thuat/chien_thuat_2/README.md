# CHIẾN THUẬT 2: BTC 15M REGIME-PULLBACK + AI META FILTER

## 1. Thông số tổng quan
- **Khung thời gian:** Nến 15 phút (`15m`) cho tín hiệu vào lệnh, Nến 1 giờ (`1h`) cho bộ lọc Macro Regime.
- **Mô hình AI:** XGBoost Meta Filter (phân loại duyệt/từ chối candidate setup theo Expected Value).
- **Vốn thử nghiệm:** `6.0 USDT` (~150k VNĐ).
- **Đòn bẩy:** `5x`.
- **Cơ chế phí:** Maker fee `0.015%`.
- **Take-profit / Stop-loss:** Thích nghi theo ATR (+1.8 ATR / -1.0 ATR).

## 2. Cấu trúc thư mục
- `config.py`: Tham số cấu hình toàn bộ chiến thuật.
- `regime.py`: Bộ lọc xu hướng vĩ mô 1H (EMA200, EMA50 Slope, ADX14).
- `setup_detector.py`: Quét setup Pullback trên khung 15m (EMA20/50, RSI 40-65, Volume).
- `features.py`: Trích xuất 17 đặc trưng kỹ thuật và gán nhãn mục tiêu theo ATR.
- `model.py`: Mô hình AI Meta Filter.
- `ev_filter.py`: Bộ lọc kỳ vọng dương (Expected Value >= 0.1R).
- `backtest_engine.py`: Engine backtest mô phỏng khớp lệnh, trượt giá và quản trị rủi ro.
- `run_backtest.py`: Script chạy backtest & stress test trượt giá độc lập.

## 3. Cách chạy kiểm thử
```bash
python run_backtest.py
```
