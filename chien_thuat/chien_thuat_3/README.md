# CHIẾN THUẬT 3: BTC 5M HFT MICROSTRUCTURE (ORDERBOOK L2 + TICK TRADES)

Chiến thuật mới nhất được nghiên cứu và phát triển từ bộ dữ liệu cao tần HFT (Level-2 Orderbook 20 tầng và Tick Trades) của Binance COIN-M Perpetual.

---

## 1. Bản chất cốt lõi của Chiến thuật 3
Khác với các chiến thuật nến truyền thống chỉ nhìn thấy giá đóng/mở và khối lượng tổng (OHLCV), Chiến thuật 3 "nhìn thấu" bức tranh vi mô của thị trường thông qua **26 đặc trưng kết hợp (Hybrid Features)** dựa trên nghiên cứu định lượng của Đại học Oxford (Albers et al., 2021):
- **14 Đặc trưng nến kỹ thuật 5m:** Động lượng (Momentum Returns lag 1..12), RSI, EMA Trend, Bollinger Band Volatility.
- **12 Đặc trưng vi cấu trúc sổ lệnh HFT (Microstructure Features):**
  1. `obi_l1`: Mất cân bằng cung cầu cấp 1 (Order Book Imbalance Top 1).
  2. `obi_l5`: Mất cân bằng cung cầu Top 5 tầng giá.
  3. `obi_l20`: Mất cân bằng toàn diện 20 tầng sổ lệnh.
  4. `obi_weighted`: **Mất cân bằng có trọng số giảm dần theo độ sâu** (Depth-Weighted OBI, triệt tiêu tường ảo).
  5. `depth_ratio`: Tỷ số thanh khoản tổng độ sâu Bid/Ask.
  6. `spread_mean`: Spread trung bình trong 5 phút (đo lường thanh khoản tức thời).
  7. `spread_vol`: Độ bất ổn của Spread (đo lường biến động vi mô).
  8. `microprice`: Giá vi mô có trọng số khối lượng (Volume-Weighted Mid-Price tại L1).
  9. `cvd`: Cumulative Volume Delta (Khối lượng Taker Buy chủ động - Taker Sell chủ động).
  10. `trade_intensity`: Mật độ / tần suất số lượt giao dịch trong 5 phút.
  11. `vwap_deviation`: Độ lệch giữa VWAP khớp lệnh thực tế so với Microprice.
  12. `large_trade_ratio`: Tỷ lệ dòng tiền từ các lệnh cá mập lớn (Top 10% volume lớn nhất).

---

## 2. Cấu trúc thư mục
- `models/`:
  - `hft_xgb_model.joblib`: Bộ não AI đã huấn luyện sẵn (Accuracy: **89.35%**, 325 KB).
- `src/`:
  - `hft_feature_builder.py`: Trích xuất 11 microstructure features từ dữ liệu thô bằng Polars.
  - `preprocess_hft.py`: Pipeline tiền xử lý dữ liệu HFT theo batch.
  - `features_v2.py`: Hợp nhất 14 technical features và 11 HFT features (chuẩn hóa tỷ lệ).
  - `model.py`: Mô hình học máy phân loại hướng nến (XGBoost / HistGradientBoosting).
  - `engine.py`: Backtest engine mô phỏng đòn bẩy, phí Maker và quản trị rủi ro.
- `train_model.py`: Script huấn luyện & đóng gói mô hình AI lưu vào `models/`.
- `paper_trader.py`: **Bot thử nghiệm Realtime** (kết nối trực tiếp Binance lấy nến 5m + L2 Orderbook 20 tầng + Trades giả lập tài khoản vốn 6 USDT).
- `run_backtest.py`: Script chạy backtest độc lập so sánh bản V1 (14 features) vs V2 (25 features HFT).

---

## 3. Cách vận hành & Thử nghiệm

### A. Chạy Bot Thử Nghiệm Realtime (Paper Trading):
Chạy bot kết nối feed Binance trực tiếp, hiển thị OBI, CVD, xác suất AI và quản lý vốn ảo 6 USDT:
```bash
python chien_thuat/chien_thuat_3/paper_trader.py
```
*(Chạy thử 1 chu kỳ kiểm tra: `python chien_thuat/chien_thuat_3/paper_trader.py --dry-run`)*

### B. Huấn luyện lại Model AI:
```bash
python chien_thuat/chien_thuat_3/train_model.py
```

### C. Chạy Kiểm Thử Backtest Lịch Sử (139 ngày):
```bash
python chien_thuat/chien_thuat_3/run_backtest.py
```

