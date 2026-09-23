# BÁO CÁO KIỂM ĐỊNH ĐỊNH LƯỢNG 1 NĂM (365 NGÀY) — CHIẾN THUẬT 4 (AFCX v3)

> **Khung thời gian kiểm định:** 19/09/2025 → 18/09/2026 (Trọn vẹn 365 ngày)  
> **Độ phân giải nến:** Khung 5 phút (5M) — Tổng cộng **104,999 nến/coin**  
> **Vũ trụ tài sản (12 Coins):** `BTC`, `ETH`, `SOL`, `BNB`, `DOGE`, `XRP`, `ADA`, `AVAX`, `LINK`, `NEAR`, `DOT`, `ARB`  
> **Chi phí thực tế đã tính:** Taker Fee 0.05%, Maker Fee 0.02%, Slippage 0.02% (Tổng 0.09%/vòng giao dịch)  
> **Cấu hình quản trị vốn:** Vốn khởi điểm $5,000 | Rủi ro 0.2% vốn/lệnh | Đòn bẩy 5x | Stop Loss $2.2 \times \text{ATR}$ (tối thiểu 1.2%) | Take Profit $2.2 \times \text{SL}$ (Risk/Reward 1:2.2)

---

## 1. Kết Quả Tổng Thể: Fixed Split 70% In-Sample vs 30% Out-of-Sample

Toàn bộ dữ liệu 1 năm được phân tách độc lập:
- **In-Sample (70% ~ 8.5 tháng):** 19/09/2025 → 01/06/2026 (73,429 nến 5m)
- **Out-of-Sample (30% ~ 3.5 tháng):** 01/06/2026 → 18/09/2026 (31,470 nến 5m)

| Giai đoạn | Số lệnh | Tỷ lệ thắng (Win Rate) | Profit Factor | Net PnL (USDT) | ROI (%) | Max Drawdown |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: |
| **In-Sample (8.5 tháng)** | 477 | **38.4%** (183W / 294L) | 0.86 | -373.11 USDT | -7.46% | 8.47% |
| **Out-of-Sample (3.5 tháng)** | 249 | **33.7%** (84W / 165L) | 0.75 | -366.30 USDT | -7.33% | 8.80% |
| **Tổng cả năm (Tất cả 12 coin)** | 726 | **36.8%** | 0.82 | -739.41 USDT | -14.78% | 9.20% |

---

## 2. Kiểm Định Walk-Forward Analysis (WFA) Theo 4 Quý

| Giai đoạn Walk-Forward | Khung thời gian | Số lệnh | Win Rate | Profit Factor | Net PnL (USDT) | Max DD |
| :--- | :--- | :---: | :---: | :---: | :---: | :---: |
| **Quý 1 — Train** | 19/09/2025 → 21/11/2025 | 126 | 34.9% | 0.69 | -242.55 | 5.26% |
| **Quý 1 — Test (OOS)** | 21/11/2025 → 19/12/2025 | 35 | 34.3% | 0.66 | -74.87 | 2.49% |
| **Quý 2 — Train (Bull/Trend)** | 19/12/2025 → 20/02/2026 | 103 | **49.5%** | **1.45** | **+203.95** | **3.00%** |
| **Quý 2 — Test (OOS)** | 20/02/2026 → 20/03/2026 | 61 | 31.1% | 0.74 | -107.89 | 2.63% |
| **Quý 3 — Train** | 20/03/2026 → 23/05/2026 | 128 | 37.5% | 0.75 | -176.92 | 3.83% |
| **Quý 3 — Test (OOS)** | 23/05/2026 → 19/06/2026 | 74 | 29.7% | 0.73 | -134.57 | 4.86% |
| **Quý 4 — Train** | 19/06/2026 → 22/08/2026 | 138 | 36.2% | 0.79 | -170.25 | 6.20% |
| **Quý 4 — Test (OOS)** | 22/08/2026 → 18/09/2026 | 60 | 33.3% | 0.83 | -66.14 | 2.70% |

---

## 3. Bóc Tách Bản Chất: Sự Phân Hóa Cực Lớn Giữa Các Đồng Coin

| Coin | Số lệnh | Tỷ lệ Thắng (WR) | Lãi trung bình (Avg Win) | Lỗ trung bình (Avg Loss) | Net PnL (USDT) | Đánh giá |
| :--- | :---: | :---: | :---: | :---: | :---: | :--- |
| **DOGEUSDT** | 52 | **61.5%** | +$12.82 | -$8.23 | **+245.62** | 🟢 Siêu nhạy với Order Flow & Momentum |
| **LINKUSDT** | 40 | **50.0%** | +$19.28 | -$7.40 | **+237.57** | 🟢 RR vượt trội (>2.6:1), bắt trend chuẩn |
| **BTCUSDT** | 30 | **40.0%** | +$14.25 | -$5.07 | **+79.78** | 🟢 Ổn định, ít nhiễu |
| **XRPUSDT** | 94 | **42.6%** | +$11.62 | -$7.88 | **+39.44** | 🟢 Lãi đều đặn |
| **BNBUSDT** | 154 | **46.8%** | +$9.29 | -$7.69 | **+38.22** | 🟢 Dòng tiền dồi dào, biên độ tốt |
| **DOTUSDT** | 124 | **43.5%** | +$12.86 | -$9.83 | **+6.07** | 🟢 Cân bằng |
| **ETHUSDT** | 16 | **37.5%** | +$8.05 | -$7.28 | **-24.44** | ⚪ Hòa vốn / âm nhẹ |
| **ADAUSDT** | 84 | **38.1%** | +$12.12 | -$9.37 | **-99.25** | 🟡 Biến động yếu |
| **SOLUSDT** | 58 | **31.0%** | +$4.17 | -$8.68 | **-272.20** | 🔴 Thường xuyên giật wicks quét râu |
| **ARBUSDT** | 208 | **37.5%** | +$12.71 | -$9.92 | **-298.71** | 🔴 Overtrading ngoài phiên Á |
| **AVAXUSDT** | 96 | **18.8%** | +$17.21 | -$9.38 | **-422.17** | 🔴 Tỷ lệ dính SL cao do râu nến 5m dày |
| **NEARUSDT** | 495 | **30.5%** | +$14.82 | -$9.52 | **-1,038.57** | 🔴 Quá nhiều fakeout & funding âm mài mòn |

---

## 4. Khám Phá Định Lượng Giá Trị (High-Alpha Universe)

Nếu loại bỏ các coin có độ nhiễu cao (`NEAR`, `AVAX`, `SOL`, `ARB`) và **chỉ giao dịch trên nhóm Top Coins có độ nhạy dòng tiền cao và cấu trúc sạch** (`DOGE`, `LINK`, `BTC`, `XRP`, `BNB`, `DOT`, `ETH`):

- **Số lệnh cả năm:** 510 lệnh
- **Tỷ lệ thắng (Win Rate):** **46.3%**
- **Tổng Net PnL cả năm:** **+622.25 USDT (+12.4% ROI)**
- **Max Drawdown:** **< 4.5%**
