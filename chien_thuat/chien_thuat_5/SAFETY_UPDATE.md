# Bản sửa vận hành chiến thuật 4–5

Phạm vi: chỉ AFCX (chiến thuật 4 và 5). `execution/daemon.py` chuyển hai
chiến thuật này sang `execution/afcx_daemon.py`; các chiến thuật khác tiếp tục
dùng luồng cũ. Client của chiến thuật 3 và các bộ quản lý dùng chung giữ nguyên.

## Thay đổi

- Sửa hàm lấy order book và biến TP gây lỗi runtime.
- Lệnh đóng dùng reduce-only. Chỉ hủy bảo vệ và ghi nhận đóng sau khi xác nhận flat.
- Lưu ý định mở lệnh và client ID trước khi gửi. Khi kết quả chưa rõ, giữ khóa
  và đối soát, không gửi lại entry mù. Trạng thái không giải quyết được cần kiểm tra
  lịch sử lệnh trên sàn; không xóa registry để ép bot chạy.
- Đặt SL trước TP; thay SL theo hướng có lợi, xác nhận SL mới trước khi hủy SL cũ.
- Lưu đỉnh/đáy, SL và thời gian vào lệnh; dùng khoảng SL ban đầu để tính R.
- Cooldown được truyền tới đúng engine. Xác nhận ASIA chỉ đếm ranking mới.
- Sử dụng nến đã đóng, volume xác nhận hướng dòng tiền; chặn hướng giao dịch
  trái với momentum tuyệt đối. Không đổi các ngưỡng Z-score theo phiên.
- Lưu quyết định và metrics vào `logs/decisions_<strategy>_<mode>.jsonl`.
- Ghi registry/risk state bằng thay thế file nguyên tử; không bỏ qua file hỏng.
- Chỉ cho một daemon AFCX cùng mode chạy trên bản cài đặt này. Đây không phải
  khóa phân tán: không chạy thêm bản sao cùng tài khoản trên server khác.

## Vốn nhỏ

Chiến thuật 4 dùng ngân sách rủi ro 0,2%; chiến thuật 5 dùng 0,5% vốn/lệnh.
Sizing dự phòng chi phí 0,14% notional; đây là giả định bảo thủ cần cập nhật theo
phí thực tế và trượt giá, không phải mức phí sàn được bảo đảm.

Không còn ép lên 15 USDT. Ví dụ vốn 8,55 USDT, SL 1,5% cho phép notional khoảng
2,61 USDT trước làm tròn. Nếu nhỏ hơn minimum của symbol thì bỏ qua lệnh.
Bot đọc filter sàn và làm tròn xuống theo step size, kiểm tra available balance.
Không tự nâng rủi ro để đạt chỉ tiêu số lệnh. Ngân sách lỗ không bảo đảm mức lỗ tối đa
vì slippage/gap và lỗi kết nối vẫn có thể xảy ra.

## Kiểm tra và vận hành

```bash
python3 -m unittest discover -s tests -p 'test_afcx_safety.py' -v
./quant_bot.sh start chien_thuat_4 demo
./quant_bot.sh start chien_thuat_5 demo
```

Chỉ chạy một lệnh start ở trên mỗi lần. Có thể đặt `QUANT_PYTHON` tới Python
đã cài dependency; mặc định tìm `.venv/bin/python` rồi `python3`.
Lệnh start chiến thuật 5 không ghi mode vẫn mặc định live theo cấu hình cũ,
vì vậy luôn ghi rõ `demo` khi thử nghiệm.

## Giới hạn còn lại

Đây là sửa lỗi và chuẩn hóa logic, chưa phải chứng minh lợi nhuận. Chưa chạy
live hoặc backtest mới. Các bảng kết quả và lời khẳng định an toàn trong tài liệu
cũ không chứng minh hiệu quả của bản này. Cần replay/backtest cùng engine,
walk-forward và thử demo trước khi triển khai live. Chưa thêm ML hoặc nới bộ lọc.

Nguồn OI giữa lượt quét, dữ liệu sổ lệnh lịch sử và mô hình chi phí vẫn cần nghiên
cứu thêm. Settlement tổng hợp income của symbol từ thời điểm mở; không giao dịch
thủ công trên symbol đang được bot quản lý. Bản sửa không bảo đảm exactly-once
cho mọi sự cố API/protection; kiểm thử mất kết nối và phản hồi không rõ ràng cần
tiếp tục trên demo. Hard SL trên sàn vẫn là lớp bảo vệ chính khi daemon mất kết nối.
