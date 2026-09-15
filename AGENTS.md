# Quy Tắc Phát Triển Chiến Thuật Mới (Trading Strategy Development Rules)

Mỗi khi người dùng (USER) yêu cầu tạo hoặc nghiên cứu bất kỳ chiến thuật giao dịch mới nào (ví dụ: `chien_thuat_4`, `chien_thuat_5`, hoặc bất kỳ chiến lược mới nào):

1. **Bắt buộc hỗ trợ chạy ngầm 24/7 (Daemon Integration)**:
   - Mọi chiến thuật mới phải kế thừa hoặc cung cấp Adapter tương thích với `BaseStrategy` trong [execution/strategy_interface.py](file:///home/tuannm/crypto_btc_quant_lab/execution/strategy_interface.py).
   - Tự động tạo adapter tại `execution/adapters/strategy_<N>.py` hoặc đặt file `strategy.py` trong thư mục chiến thuật đó để hệ thống [execution/registry.py](file:///home/tuannm/crypto_btc_quant_lab/execution/registry.py) **tự động phát hiện (Auto-Discovery)**.

2. **Khả năng vận hành độc lập (Unattended Background Execution)**:
   - Chiến thuật mới phải chạy được ngay lập tức bằng lệnh trung tâm:
     ```bash
     ./quant_bot.sh start <tên_chiến_thuật>
     ```
   - Phải tự động quản lý vị thế, tự cài TP (Take Profit) & SL (Stop Loss), tự ghi log vào `logs/live_<tên_chiến_thuật>.log`.
   - Phải hoạt động bền bỉ, độc lập trên server Linux ngay cả khi người dùng tắt máy tính cá nhân, ngắt kết nối SSH hoặc đi ngủ.
