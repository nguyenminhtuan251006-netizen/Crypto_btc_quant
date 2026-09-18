# CHIẾN THUẬT 5: AFCX Micro-Capital Edition (Tối ưu vốn 150.000 VNĐ / ~6 USDT)

## 1. Giới thiệu
Chiến thuật 5 được tùy biến đặc biệt từ mô típ định lượng **AFCX v3 Dual-Session Architecture (Chiến thuật 4)** nhưng được tinh chỉnh để chạy hiệu quả và an toàn tuyệt đối với số vốn siêu nhỏ: **từ 150.000 VNĐ (~6 USDT)** trên sàn Binance Futures thật hoặc demo.

## 2. Các điểm cải tiến chuyên biệt
* **Vị thế sàn tối thiểu (Floor Notional Clamp)**:
  * Tự động ép giá trị vị thế mỗi lệnh lên mức tối thiểu **5.5 USDT** để vừa vặn vượt ngưỡng sàn Binance `MIN_NOTIONAL` (5.0 USDT).
  * Ký quỹ thực tế (Margin 5x): Chỉ tốn **~1.1 USDT** (~27.000 VNĐ)/lệnh. Vốn 6 USDT vẫn còn dư **~4.9 USDT** làm đệm an toàn.
* **Tỷ lệ rủi ro kiểm soát**:
  * Nếu dính Stop Loss (-1.5% ATR): Mất tối đa **0.0825 USDT (~2.000 VNĐ)**.
  * Nếu đạt Take Profit (+2.5%): Lãi khoảng **0.1375 USDT (~3.500 VNĐ)**.
  * Phí giao dịch sàn: ~100 VNĐ/vòng lệnh (lãi 3.500đ nuốt trọn phí).
* **Vũ trụ Altcoin Micro-Capital**:
  * Tập trung vào Top Altcoin thanh khoản cao nhất Binance hỗ trợ `minNotional = 5.0 USDT` (ARB, OP, SUI, DOGE, XRP, ADA, AVAX, LINK, NEAR, SOL, ETH...).

## 3. Cách vận hành độc lập 24/7
Chạy chiến thuật 5 bằng lệnh:
```bash
./quant_bot.sh start chien_thuat_5
```

Kiểm tra trạng thái:
```bash
./quant_bot.sh status
```

Xem nhật ký thời gian thực:
```bash
./quant_bot.sh logs
```
