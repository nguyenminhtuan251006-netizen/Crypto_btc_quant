# AFCX v3 — DUAL SESSION ARCHITECTURE
## Adaptive Flow-Centric Cross-Sectional Strategy
### Thiết kế 2 profile giao dịch không xung đột

---

## 1. Mục tiêu thiết kế

AFCX v3 giữ nguyên một chiến thuật lõi duy nhất, nhưng chia quyền mở lệnh thành hai profile theo thời gian:

| Profile | Giờ Việt Nam | UTC | Vai trò |
|---|---:|---:|---|
| **AFCX-LIQUID** | 15:00 → 04:00 | 08:00 → 21:00 | Profile hiện tại, ưu tiên phiên Âu–Mỹ |
| **AFCX-ASIA** | 04:00 → 15:00 | 21:00 → 08:00 | Profile bổ sung cho ngoài giờ của bot hiện tại |

Mục tiêu:

- AFCX có thể săn cơ hội trong toàn bộ 24 giờ.
- Hai profile không được mở lệnh chồng lên nhau.
- Hai profile không được hủy TP/SL của nhau.
- Một vị thế đang chạy phải tiếp tục do đúng profile đã mở nó quản lý.
- Giữ nguyên triết lý AFCX: tối đa 1 vị thế tại một thời điểm.
- Chỉ có một lớp trung tâm được phép gửi lệnh trực tiếp đến Binance.

---

## 2. Phân chia phiên giao dịch

### 2.1. AFCX-ASIA

```python
04:00:00 <= VN_TIME < 15:00:00
```

### 2.2. AFCX-LIQUID

```python
VN_TIME >= 15:00:00 or VN_TIME < 04:00:00
```

Hai vùng thời gian dùng quy tắc nửa kín nửa mở để không xuất hiện thời điểm cả hai profile cùng có quyền entry.

```text
00:00              04:00                  15:00             24:00
|--------------------|----------------------|-------------------|
     AFCX-LIQUID            AFCX-ASIA             AFCX-LIQUID
```

---

## 3. AFCX-ASIA vẫn thuộc cùng chiến thuật AFCX

AFCX-ASIA không phải chiến thuật mới.

Nó giữ nguyên lõi:

- Dynamic Top 20 Liquid Universe
- Cross-Sectional Relative Strength
- Momentum 1h / 4h
- OFI 15m
- Delta Open Interest
- Orderbook Imbalance
- Relative Volume
- Net Momentum
- Crowding Penalty
- Market Regime
- Confidence Gate
- Consensus Gate
- Cost Gate
- Dynamic Exit
- Risk Management
- Kill Switch

Công thức Direction Score giữ nguyên:

\[
D_i =
0.20Z(m_{1h})
+0.15Z(m_{4h})
+0.25Z(OFI_{15m})
+0.15Z(\Delta OI)
+0.10Z(BookImb)
+0.10Z(RelVol)
+0.05NetMom
\]

Crowding Penalty giữ nguyên:

\[
C_i =
0.60\max(0,Z(FundingRate_i))
+
0.40\max(0,Z(Basis_i))
\]

Final Score:

```text
LONG:
S_i = D_i - C_i

SHORT:
S_i = D_i + C_i
```

Sau đó chuẩn hóa Z-Score toàn bộ universe và chọn Top 1.

---

## 4. Session Profile riêng cho AFCX-ASIA

AFCX-ASIA sử dụng cùng Alpha Engine nhưng có Entry Gate khắt khe hơn.

### 4.1. AFCX-LIQUID

```text
TREND:
|Z| >= 1.25

RANGE:
|Z| >= 1.35

Confidence Gap:
>= 0.20

Consensus:
>= 4/6

Expected Edge:
>= 2.5 x Total Trading Cost
```

### 4.2. AFCX-ASIA

Giá trị khởi tạo đề xuất để backtest:

```text
TREND:
|Z| >= 1.40

RANGE:
|Z| >= 1.55

Confidence Gap:
>= 0.30

Consensus:
>= 5/6

Expected Edge:
>= 3.0 x Total Trading Cost
```

Các ngưỡng trên là tham số khởi tạo để backtest và tối ưu, không phải giá trị cố định bắt buộc cho production.

---

## 5. Persistence Gate cho phiên ASIA

AFCX-ASIA nên có thêm Persistence Gate để giảm tín hiệu giả trong giai đoạn thanh khoản mỏng.

Điều kiện:

- Top 1 phải giữ cùng symbol.
- Giữ cùng hướng LONG hoặc SHORT.
- Tồn tại qua tối thiểu 2 lần refresh Cross-Sectional liên tiếp.

Ví dụ hợp lệ:

```text
08:12
SUIUSDT
TOP 1 LONG
Z = +1.71

08:14
SUIUSDT
TOP 1 LONG
Z = +1.66

=> PASS
```

Ví dụ bị loại:

```text
08:12
SUIUSDT LONG

08:14
APTUSDT SHORT

=> REJECT
```

---

## 6. Kiến trúc thực thi bắt buộc

Không nên để hai bot cùng trực tiếp điều khiển tài khoản Binance.

### Không dùng

```text
AFCX-LIQUID ---> Binance
AFCX-ASIA   ---> Binance
```

### Dùng

```text
                  AFCX CORE
                     |
        +------------+------------+
        |                         |
 AFCX-LIQUID ENGINE         AFCX-ASIA ENGINE
        |                         |
        +------------+------------+
                     |
               SESSION ARBITER
                     |
               SIGNAL ARBITER
                     |
              GLOBAL TRADE LOCK
                     |
             POSITION OWNERSHIP
                     |
              ORDER REGISTRY
                     |
               RISK MANAGER
                     |
             BINANCE EXECUTOR
                     |
                  BINANCE
```

Chỉ `BINANCE EXECUTOR` hoặc `AFCX COORDINATOR` được phép gửi lệnh đến Binance.

Hai engine chỉ tạo tín hiệu.

---

## 7. Global Position Lock

AFCX giữ nguyên nguyên tắc:

```text
MAX_OPEN_POSITIONS = 1
```

Nếu bất kỳ profile nào đang sở hữu vị thế:

```text
GLOBAL_POSITION_LOCK = TRUE
```

Profile còn lại:

```text
SCAN = ON
ENTRY = OFF
```

Khi vị thế đóng hoàn toàn:

```text
GLOBAL_POSITION_LOCK = FALSE
```

Profile đang ở đúng session hiện tại mới được quyền tranh suất entry tiếp theo.

---

## 8. Position Ownership

Mọi vị thế phải có owner.

Ví dụ:

```yaml
trade_id: AFCX-LIQUID-20260916-SUI-001
owner: LIQUID
symbol: SUIUSDT
side: LONG
status: OPEN
entry_order_id: ...
sl_order_id: ...
tp_order_id: ...
entry_time: ...
```

Hoặc:

```yaml
trade_id: AFCX-ASIA-20260916-APT-002
owner: ASIA
symbol: APTUSDT
side: SHORT
status: OPEN
entry_order_id: ...
sl_order_id: ...
tp_order_id: ...
entry_time: ...
```

Quy tắc:

```text
Profile nào mở trade
=> profile đó sở hữu trade
=> profile đó quản lý Dynamic Exit
=> profile đó quản lý TP/SL
=> profile khác tuyệt đối không được sửa hoặc hủy order của trade đó
```

---

## 9. Quy tắc chuyển giao giữa hai phiên

### Trường hợp 1: LIQUID mở vị thế trước 04:00

Ví dụ:

```text
03:37
AFCX-LIQUID mở LONG NEARUSDT

04:00
Session ASIA bắt đầu
```

Trạng thái:

```text
LIQUID:
NEW ENTRY = OFF
POSITION MANAGEMENT = ON

ASIA:
SCAN = ON
NEW ENTRY = BLOCKED
```

LIQUID tiếp tục quản lý NEAR cho đến khi trade đóng.

Ví dụ:

```text
04:26
NEAR đóng hoàn toàn
```

Khi đó:

```text
GLOBAL_POSITION_LOCK = FALSE
```

ASIA mới được quyền mở vị thế mới.

---

### Trường hợp 2: ASIA mở vị thế trước 15:00

Ví dụ:

```text
14:48
AFCX-ASIA mở SHORT APTUSDT

15:00
Session LIQUID bắt đầu
```

Trạng thái:

```text
ASIA:
NEW ENTRY = OFF
POSITION MANAGEMENT = ON

LIQUID:
SCAN = ON
NEW ENTRY = BLOCKED
```

Khi APT đóng hoàn toàn, quyền entry mới được chuyển cho LIQUID.

---

## 10. Client Order ID Convention

Mọi order phải có namespace riêng.

### AFCX-LIQUID

```text
AFCX-LIQ-E-000124
AFCX-LIQ-SL-000124
AFCX-LIQ-TP-000124
```

### AFCX-ASIA

```text
AFCX-ASI-E-000125
AFCX-ASI-SL-000125
AFCX-ASI-TP-000125
```

Quy ước:

```text
LIQ = AFCX-LIQUID
ASI = AFCX-ASIA

E  = Entry
SL = Stop Loss
TP = Take Profit
```

---

## 11. Order Registry

Coordinator phải lưu registry cho toàn bộ trade.

Ví dụ:

```json
{
  "trade_id": "AFCX-LIQUID-20260916-SUI-001",
  "owner": "LIQUID",
  "symbol": "SUIUSDT",
  "entry_order_id": 123456,
  "sl_order_id": 123457,
  "tp_order_id": 123458,
  "status": "OPEN"
}
```

Mọi hành động cancel phải thực hiện bằng đúng:

```text
orderId
```

hoặc:

```text
origClientOrderId
```

thuộc trade đó.

---

## 12. Cấm Cancel All trong Normal Mode

Trong chế độ bình thường:

```text
DO NOT:
cancel_all_open_orders(symbol)
```

Vì một lệnh thuộc profile khác có thể bị hủy nhầm.

### Chỉ cho phép

```text
cancel(order_id)
```

hoặc:

```text
cancel(origClientOrderId)
```

`Cancel All Open Orders` chỉ được sử dụng trong:

```text
GLOBAL EMERGENCY KILL SWITCH
```

---

## 13. Zero-Orphan Reconciler mới

Logic cũ kiểu:

```python
if no_position(symbol):
    cancel_orders(symbol)
```

không được sử dụng.

Logic mới:

```python
for trade in own_trades:

    if trade.position_closed:

        cancel(trade.sl_order_id)
        cancel(trade.tp_order_id)

        mark_trade_closed(trade.trade_id)
```

Nguyên tắc:

```text
Mỗi profile chỉ dọn order thuộc chính trade của mình.
```

Không được coi một order lạ là orphan chỉ vì engine hiện tại không nhận ra nó.

---

## 14. Dynamic Exit giữ nguyên

Cả hai profile dùng chung Dynamic Exit:

```text
Profit >= 1.0R
=> Move SL to Breakeven

Profit >= 1.4R
=> Activate Dynamic Trailing Stop

Alpha Score Decay > 50%
=> Early Exit

Drop out of Top 5
=> Early Exit

OFI / Flow Sign Flip
=> Market Exit

Holding Time >= 180 minutes
=> Time Stop

Hard SL / TP hit
=> Exchange Exit
```

Profile ownership vẫn được giữ cho đến khi vị thế đóng hoàn toàn.

---

## 15. State Machine đề xuất

Hệ thống có các trạng thái:

```text
ASIA_ACTIVE
LIQUID_ACTIVE
LEGACY_POSITION_MANAGEMENT
FLAT_HANDOFF
GLOBAL_KILL
```

### ASIA_ACTIVE

```text
04:00 <= VN_TIME < 15:00
No existing position
ASIA has entry authority
```

### LIQUID_ACTIVE

```text
VN_TIME >= 15:00
OR VN_TIME < 04:00

No existing position
LIQUID has entry authority
```

### LEGACY_POSITION_MANAGEMENT

Profile đã hết session nhưng vẫn còn position.

Ví dụ:

```text
04:10
Owner = LIQUID
Session = ASIA
```

LIQUID tiếp tục quản lý vị thế.

ASIA chỉ scan.

### FLAT_HANDOFF

Vị thế cũ vừa đóng.

Coordinator:

```text
release_global_lock()
detect_current_session()
enable_entry_for_active_profile()
```

### GLOBAL_KILL

Kích hoạt khi:

```text
Daily Loss >= 3%
OR
Account Drawdown >= 6%
OR
Critical Exchange/Reconciliation Error
```

Hành động:

```text
Close positions
Cancel protective orders
Cancel remaining AFCX orders
Disable both session profiles
Require manual or controlled restart
```

---

## 16. Pseudocode tổng thể

```python
def resolve_session(vn_time):
    if time(4, 0) <= vn_time.time() < time(15, 0):
        return "ASIA"
    return "LIQUID"


def trading_loop():

    session = resolve_session(now_vietnam())

    reconcile_exchange_state()

    if global_kill_switch_triggered():
        execute_global_kill()
        return

    if global_position_exists():

        owner = get_position_owner()

        owner.manage_open_position()

        other = other_profile(owner)
        other.scan_only()

        return

    release_global_position_lock()

    active_engine = get_engine(session)

    signal = active_engine.scan_market()

    if not signal:
        return

    if not active_engine.session_filters_pass(signal):
        return

    if not global_risk_manager_allows(signal):
        return

    if not acquire_global_position_lock():
        return

    trade = coordinator.open_trade(
        owner=session,
        signal=signal
    )

    register_trade(trade)
```

---

## 17. Entry Flow

```text
Market Data
   |
   v
Top 20 Universe
   |
   v
AFCX Core Score
   |
   v
Top 1 Candidate
   |
   v
Market Regime Gate
   |
   v
Confidence Gate
   |
   v
Consensus Gate
   |
   v
Cost Gate
   |
   v
Session Specific Gate
   |
   +---- ASIA --> Persistence Gate
   |
   v
Global Position Lock Check
   |
   v
Risk Manager
   |
   v
Coordinator
   |
   v
Entry + TP + SL
```

---

## 18. Conflict Prevention Rules

### Rule 1

```text
Only one profile has NEW ENTRY authority at a time.
```

### Rule 2

```text
Only one AFCX position may exist at a time.
```

### Rule 3

```text
An existing position remains owned by the profile that opened it,
even after its entry session has ended.
```

### Rule 4

```text
The other profile may scan,
but may not open another trade while Global Position Lock is active.
```

### Rule 5

```text
A profile may cancel only orders registered to trades it owns.
```

### Rule 6

```text
No engine may use Cancel All during normal operation.
```

### Rule 7

```text
Only Coordinator talks to Binance for trade execution.
```

### Rule 8

```text
Session boundary does NOT force-close a live trade.
```

### Rule 9

```text
Dynamic Exit continues until the position is fully closed.
```

### Rule 10

```text
After a trade closes, the profile currently in-session receives entry authority.
```

---

## 19. Cấu trúc module đề xuất

```text
afcx/
|
+-- core/
|   +-- universe.py
|   +-- flow_features.py
|   +-- scoring.py
|   +-- crowding.py
|   +-- regime.py
|   +-- ranker.py
|
+-- sessions/
|   +-- liquid_profile.py
|   +-- asia_profile.py
|   +-- session_router.py
|
+-- gates/
|   +-- regime_gate.py
|   +-- confidence_gate.py
|   +-- consensus_gate.py
|   +-- cost_gate.py
|   +-- persistence_gate.py
|
+-- execution/
|   +-- coordinator.py
|   +-- binance_executor.py
|   +-- order_registry.py
|   +-- position_owner.py
|   +-- global_lock.py
|
+-- risk/
|   +-- risk_manager.py
|   +-- circuit_breaker.py
|   +-- exposure_manager.py
|
+-- exit/
|   +-- dynamic_exit.py
|   +-- trailing.py
|   +-- breakeven.py
|   +-- score_decay.py
|   +-- sign_flip.py
|   +-- time_stop.py
|
+-- reconciliation/
|   +-- exchange_reconciler.py
|   +-- orphan_cleaner.py
|
+-- state/
    +-- trade_store.py
    +-- session_state.py
```

---

## 20. Cấu hình mẫu

```yaml
strategy:
  name: AFCX
  version: 3.0

global:
  max_open_positions: 1
  global_position_lock: true
  coordinator_only_execution: true

sessions:

  liquid:
    enabled: true
    start_vn: "15:00"
    end_vn: "04:00"

    trend_z_min: 1.25
    range_z_min: 1.35
    confidence_gap_min: 0.20
    consensus_min: 4
    cost_multiple_min: 2.5

  asia:
    enabled: true
    start_vn: "04:00"
    end_vn: "15:00"

    trend_z_min: 1.40
    range_z_min: 1.55
    confidence_gap_min: 0.30
    consensus_min: 5
    cost_multiple_min: 3.0

    persistence:
      enabled: true
      required_consecutive_ranks: 2

execution:

  order_namespace:
    liquid: "AFCX-LIQ"
    asia: "AFCX-ASI"

  allow_cancel_all_normal_mode: false

  ownership_enforced: true

dynamic_exit:

  breakeven_trigger_r: 1.0
  trailing_trigger_r: 1.4
  trailing_profit_lock: 0.70
  score_decay_exit: 0.50
  time_stop_minutes: 180

risk:

  max_daily_loss_pct: 3.0
  max_account_drawdown_pct: 6.0
  default_leverage: 5
```

---

## 21. Kết luận kiến trúc

AFCX v3 nên được coi là:

```text
ONE STRATEGY
TWO SESSION PROFILES
ONE GLOBAL POSITION
ONE COORDINATOR
ONE ORDER REGISTRY
ONE RISK MANAGER
```

Tức là:

```text
AFCX-LIQUID
15:00 -> 04:00
```

và:

```text
AFCX-ASIA
04:00 -> 15:00
```

không phải hai chiến thuật cạnh tranh nhau.

Chúng là hai profile thời gian của cùng hệ thống AFCX.

Thời gian chỉ quyết định:

```text
WHO MAY OPEN THE NEXT TRADE
```

Còn ownership quyết định:

```text
WHO MUST MANAGE THE CURRENT TRADE
```

Đây là nguyên tắc cốt lõi để hai profile không:

- mở lệnh chồng nhau;
- đóng vị thế của nhau;
- hủy Stop Loss của nhau;
- hủy Take Profit của nhau;
- tranh quyền quản lý cùng một position;
- phá Zero-Orphan Reconciler của nhau.

---

## 22. Nguyên tắc production quan trọng nhất

```text
SESSION decides ENTRY AUTHORITY.

OWNERSHIP decides POSITION MANAGEMENT.

GLOBAL LOCK prevents simultaneous exposure.

ORDER REGISTRY prevents accidental cancellation.

COORDINATOR is the only gateway to Binance.
```
