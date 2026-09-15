# Quy Tắc Tự Động Đăng Ký Chiến Thuật Mới Chạy Ngầm

Khi tạo bất kỳ chiến thuật mới nào trong hệ thống `crypto_btc_quant_lab`:
1. Luôn tự động tạo Adapter hoặc triển khai `BaseStrategy` để [execution/registry.py](file:///home/tuannm/crypto_btc_quant_lab/execution/registry.py) tự động nhận diện.
2. Đảm bảo chiến thuật chạy ngầm được 24/7 độc lập với máy cá nhân của người dùng qua `./quant_bot.sh start <tên_chiến_thuật>`.
