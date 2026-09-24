# CHIẾN THUẬT 5: AFCX Micro-Capital Edition (Tối ưu vốn ~6–50 USDT)

> Cập nhật: xem [SAFETY_UPDATE.md](SAFETY_UPDATE.md) cho hành vi hiện tại.
> Các con số floor 15 USDT, lỗ tối đa 0,09 USDT và khẳng định an toàn dưới đây
> thuộc thiết kế cũ, không còn là cam kết của bản đã sửa. Bản mới bỏ qua lệnh
> nếu lượng tối thiểu trên sàn vượt ngân sách rủi ro.

## 1. Giới thiệu
Chiến thuật 5 được tùy biến đặc biệt từ mô típ định lượng **AFCX v3 Dual-Session Architecture (Chiến thuật 4)** nhưng được tinh chỉnh để chạy hiệu quả và an toàn tuyệt đối với số vốn siêu nhỏ: **từ 6 USDT (~150.000 VNĐ)** trên sàn Binance Futures thật hoặc demo.

## 2. Các điểm cải tiến chuyên biệt
* **Vị thế sàn tối thiểu (Floor Notional Clamp)**:
  * Tự động ép giá trị vị thế mỗi lệnh lên mức tối thiểu **15.0 USDT** để vượt ngưỡng sàn Binance `MIN_NOTIONAL` (5.0 USDT) với biên an toàn.
  * Ký quỹ thực tế (Margin 10x): Chỉ tốn **~1.5 USDT** (~38.000 VNĐ)/lệnh. Vốn 8.5 USDT vẫn còn dư **~7.0 USDT** làm đệm an toàn.
* **Tỷ lệ rủi ro kiểm soát**:
  * Nếu dính Stop Loss (-0.6%): Mất tối đa **~0.09 USDT (~2.300 VNĐ)**.
  * Nếu đạt Take Profit (+1.2%): Lãi khoảng **~0.18 USDT (~4.500 VNĐ)**.
  * Reward:Risk = **2:1** — Chỉ cần thắng 40% lệnh đã có lãi.
  * Phí giao dịch sàn: ~0.003 USDT/vòng lệnh (lãi 0.18 USDT nuốt trọn phí).
* **Trailing Take Profit 2 tầng (Chống quét râu)**:
  * Tầng 1 (+1.2%): Ghim SL tại +1.0% bảo hộ lãi cứng.
  * Tầng 2 (+1.8%): Bám đỉnh với callback 0.45%.
  * Trần khẩn cấp +8.0%.
* **Vũ trụ Altcoin Micro-Capital**:
  * Tập trung vào Top 15 Altcoin thanh khoản cao nhất Binance Futures hỗ trợ `minNotional = 5.0 USDT` (ETH, SOL, ARB, OP, XRP, DOGE, ADA, AVAX, SUI, LINK, NEAR, APT, INJ, BNB, LTC).

> **Lưu ý về Risk Override:** Do min_notional floor (15 USDT) ép vị thế lên cao hơn formula risk-based, rủi ro thực tế mỗi lệnh là ~1.05% vốn (thay vì 0.5% theo Risk Model). Đây là trade-off cần thiết cho micro-capital mode và vẫn nằm trong ngưỡng an toàn.

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
