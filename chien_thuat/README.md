# TRUNG TÂM CHIẾN THUẬT GIAO DỊCH ĐỊNH LƯỢNG (QUANT LAB STRATEGIES)

Hệ thống quản lý và nghiên cứu 3 chiến thuật giao dịch định lượng cho Bitcoin Futures trên sàn Binance.

---

## 1. Danh mục 3 Chiến Thuật

| Thư mục | Tên chiến thuật | Khung nến | Nguồn dữ liệu & Cốt lõi | Trọng tâm & Điểm mạnh |
| :--- | :--- | :---: | :--- | :--- |
| [`chien_thuat_1/`](file:///home/tuannm/crypto_btc_quant_lab/chien_thuat/chien_thuat_1) | **Chiến thuật 1: BTC 5M XGBoost High-Conviction** | `5m` | Nến kỹ thuật 5m thuần túy (14 features: RSI, EMA, Volatility) | Săn lệnh phiên London & New York (15:00 - 02:00 VN), bộ lọc xu hướng EMA50, ngưỡng tự tin Top 10% |
| [`chien_thuat_2/`](file:///home/tuannm/crypto_btc_quant_lab/chien_thuat/chien_thuat_2) | **Chiến thuật 2: BTC 15M Regime-Pullback + AI Meta Filter** | `15m` / `1h` | Nến 15m & 1h (Macro Regime EMA200/ADX + 17 features Pullback) | Bắt sóng hồi Pullback theo xu hướng lớn, lọc nhiễu qua mô hình AI Meta Filter duyệt Expected Value (EV >= 0.1R) |
| [`chien_thuat_3/`](file:///home/tuannm/crypto_btc_quant_lab/chien_thuat/chien_thuat_3) | **Chiến thuật 3 (MỚI NHẤT): BTC 5M HFT Microstructure** | `5m` | Nến 5m + Dữ liệu cao tần HFT (Sổ lệnh L2 20 tầng + Tick Trades) $\rightarrow$ 25 features | Nhìn thấu vi cấu trúc sổ lệnh (OBI, Microprice, CVD, Depth Ratio), nâng độ chính xác dự đoán hướng nến lên **89.35%** |

---

## 2. Hướng Dẫn Chạy Kiểm Thử Độc Lập

1. **Chiến thuật 1 (Nến 5m cơ bản):**
   ```bash
   python chien_thuat/chien_thuat_1/run_backtest_btc.py
   ```

2. **Chiến thuật 2 (15m Pullback + AI Meta Filter):**
   ```bash
   python chien_thuat/chien_thuat_2/run_backtest.py
   ```

3. **Chiến thuật 3 (MỚI NHẤT - HFT Microstructure):**
   ```bash
   python chien_thuat/chien_thuat_3/run_backtest.py
   ```

---

## 3. Dữ Liệu Dùng Chung
Tất cả các chiến thuật đọc dữ liệu chung được lưu tập trung tại:
- `data/BTCUSDT_5m_50k.csv`: Dữ liệu 50,000 nến 5m lịch sử.
- `data/hft_features_5m.parquet`: Dữ liệu 37,842 intervals HFT 11 microstructure features đã tổng hợp.
- `reports/`: Lưu trữ kết quả và log giao dịch chi tiết.
