# CHIẾN THUẬT 1: BTC 5M XGBOOST HIGH-CONVICTION (LONDON & NY SESSIONS)

Dự án nghiên cứu & kiểm thử định lượng theo chỉ đạo của anh **Vũ Xuân Tùng** dành cho giao dịch Bitcoin Futures trên sàn **Binance**.

---

## 1. Thông Số Tổng Quan Chiến Thuật

| Tham số | Giá trị thiết lập | Giải thích ý nghĩa |
| :--- | :--- | :--- |
| **Thị trường** | `BTCUSDT` Futures (Binance) | Hợp đồng tương lai Bitcoin |
| **Khung thời gian** | **Nến 5 phút (`5m`)** | Nhịp giao dịch trong ngày tốc độ cao |
| **Mô hình AI** | **Gradient Boosting (`XGBoost`)** | Học máy phân loại nhị phân (Polymarket Up/Down) |
| **Vốn thử nghiệm** | **`6.0 USDT` (~150,000 VNĐ)** | Mức vốn tối thiểu an toàn để trải nghiệm |
| **Đòn bẩy** | **`5x` (Cross/Isolated Margin)** | Cân bằng hoàn hảo giữa lực kéo lợi nhuận và an toàn vốn |
| **Cơ chế phí** | Phí Maker hợp đồng Quý (`0.015%`) | Tiết kiệm hơn 60% so với phí Taker thông thường |
| **Tỷ lệ Lời/Lỗ (R/R)** | **`2.4 : 1`** | Ăn dày khi đúng, cắt lỗ cực nhỏ khi sai |

---

## 2. Quy Trình Vận Hành "4 Bước Vàng"

### Bước 1: Khung Giờ Đi Săn (Timing Filter)
* **Giờ hoạt động:** Chỉ săn lệnh từ **`15:00 chiều đến 02:00 sáng`** (giờ Việt Nam).
  - Đây là thời điểm phiên giao dịch **London** và **New York (Phố Wall)** mở cửa cùng các dòng tiền ETF Bitcoin hoạt động mạnh nhất. Thị trường có sóng lớn, thanh khoản dồi dào, trượt giá bằng 0.
* **Giờ nghỉ:** Từ **`02:00 sáng đến 15:00 chiều`**, bot hoàn toàn đứng ngoài để tránh các cây nến giật râu, sideway bào mòn phí của phiên Châu Á.

### Bước 2: Đi Thuận Xu Hướng Lớn (Trend Filter)
* Sử dụng đường trung bình động hàm mũ **`EMA 50`** trên nến 5m:
  - Giá nằm **TRÊN** EMA 50 $\rightarrow$ Bot **chỉ tìm điểm MUA (LONG)**.
  - Giá nằm **DƯỚI** EMA 50 $\rightarrow$ Bot **chỉ tìm điểm BÁN (SHORT)**.
  - Tuyệt đối không bao giờ đánh ngược xu hướng chính trong ngày.

### Bước 3: Trí Tuệ Nhân Tạo Duyệt Lệnh (AI XGBoost Filter)
* Mỗi 5 phút, mô hình phân tích 14 đặc trưng kỹ thuật:
  - Đà quán tính giá (Returns lag 1, 2, 3, 6, 12 nến).
  - Độ nén thân nến và bóng nến (Body, Upper/Lower Shadow).
  - Đột biến khối lượng (Volume Spike).
  - Độ lệch chuẩn dải Bollinger & RSI.
* **Ngưỡng vào lệnh (High-Conviction):** Bot chỉ kích hoạt lệnh khi xác suất dự đoán của AI nằm trong nhóm **Top 10% cao nhất**. Nếu xác suất dưới ngưỡng này, bot kiên nhẫn đứng ngoài.

### Bước 4: Quản Trị Rủi Ro & Chốt Lời / Cắt Lỗ Kỷ Luật
* **Cắt lỗ cứng (Stop Loss: `-0.5%` giá BTC):**
  - Khi dự đoán sai, bot lập tức cắt lỗ. Với vốn 150k (đòn bẩy 5x), mỗi lệnh thua **chỉ mất tối đa `~3.700 VNĐ`** (chưa bằng cốc trà đá).
* **Chốt lời kỳ vọng (Take Profit: `+1.2%` giá BTC):**
  - Khi dự đoán đúng, bot gồng lãi chạm target, bỏ túi **`~9.000 VNĐ`** (gấp 2.4 lần số tiền chấp nhận mất).
* **Đóng lệnh theo thời gian (Timeout):** Sau tối đa **90 phút (18 nến 5m)**, nếu giá vẫn chưa chạm TP hay SL thì bot tự động đóng vị thế để bảo toàn vốn.

---

## 3. Kết Quả Kiểm Thử Thực Tế (50,000 Nến ~ 6 Tháng Lịch Sử Binance)

Kiểm thử độc lập trên tập dữ liệu Out-of-Sample (dữ liệu mới 52 ngày từ 19/07/2026 đến 09/09/2026):

```text
========================================================================================
             KẾT QUẢ KIỂM THỬ OUT-OF-SAMPLE (DỮ LIỆU THỰC TẾ BINANCE)
========================================================================================
-> Vốn khởi điểm:             6.00 USDT (150,000 VNĐ)
-> Vốn kết thúc:              7.54 USDT (190,000 VNĐ)
-> Lợi nhuận ròng:            +25.62% (+40,000 VNĐ sau khi trừ sạch thuế phí)
-> Hệ số an toàn Sharpe:      4.44 (Mức rất cao trong định lượng)
-> Tỷ lệ Thắng (Win Rate):    46.39% (với tỷ lệ R/R 2.4 : 1, lãi lớn vượt trội)
-> Profit Factor:             1.12
-> Tần suất lệnh:             166 lệnh / 52 ngày (~3 lệnh/ngày vào chiều và tối)
========================================================================================
```

---

## 4. Hướng Dẫn Vận Hành Bot

### A. Chạy Giả Lập Realtime (Paper Trading - Không mất tiền thật)
```bash
python3 crypto_btc_quant_lab/paper_trader.py
```
* Bot tự động kết nối máy chủ Binance, đọc giá Bitcoin thực tế mỗi 30 giây, in khuyến nghị lệnh và nhảy số vốn giả lập trên màn hình.
* Bấm **`Ctrl + C`** để dừng bot bất cứ lúc nào.

### B. Chạy Lại Kiểm Thử Lịch Sử (Backtest)
```bash
python3 crypto_btc_quant_lab/run_backtest_btc.py
```

### C. Khi Sẵn Sàng Giao Dịch Bằng 150k Tiền Thật
1. Nạp 150.000 VNĐ vào Binance (qua Binance P2P đổi lấy ~6 USDT).
2. Chuyển USDT vào ví *Futures*.
3. Tạo API Key trên Binance: chỉ tick chọn `Enable Futures Trading`, **tuyệt đối không bật `Enable Withdrawals`**.
4. Cắm API Key vào bot để bot tự động gửi lệnh thật lên sàn.
