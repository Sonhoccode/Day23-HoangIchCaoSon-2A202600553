# Day 08 Lab Report

## 1. Team / student

- Name: Hoang Ich Cao Son
- MSSV: 2A202600553

## 2. Architecture

Graph sử dụng `StateGraph` với các node `intake`, `classify`, `tool`, `evaluate`, `answer`, `clarify`, `risky_action`, `approval`, `retry`, `dead_letter`, `finalize`. `classify` quyết định route bằng LLM, sau đó các conditional edge điều phối nhánh `simple`, `tool`, `missing_info`, `risky`, `error` và đảm bảo mọi đường đi đều kết thúc tại `finalize -> END`.

## 3. State schema

| Field | Reducer | Why |
|---|---|---|
| messages | append | lưu log ngắn theo từng bước |
| tool_results | append | giữ lịch sử kết quả tool, gồm cả retry |
| errors | append | theo dõi lỗi transient và lỗi cuối cùng |
| events | append | audit trail cho grading và debug |
| route | overwrite | chỉ có một route hiện hành |
| evaluation_result | overwrite | điều khiển retry loop sau evaluate |
| pending_question | overwrite | câu hỏi clarify cuối cùng |
| proposed_action | overwrite | mô tả hành động rủi ro trước approval |
| approval | overwrite | quyết định HITL gần nhất |

## 4. Scenario results

| Scenario | Expected route | Actual route | Success | Retries | Interrupts |
|---|---|---|---:|---:|---:|
| S01_simple | simple | simple | yes | 0 | 0 |
| S02_tool | tool | tool | yes | 0 | 0 |
| S03_missing | missing_info | missing_info | yes | 0 | 0 |
| S04_risky | risky | risky | yes | 0 | 1 |
| S05_error | error | error | yes | 2 | 0 |
| S06_delete | risky | risky | yes | 0 | 1 |
| S07_dead_letter | error | error | yes | 1 | 0 |

## 5. Failure analysis

1. Retry or tool failure: khi tool trả về lỗi, `evaluate` đặt `evaluation_result=needs_retry` để chuyển sang `retry`; `retry` tăng `attempt` và route bị chặn bởi `max_attempts` để tránh loop vô hạn.
2. Risky action without approval: các yêu cầu refund, delete, send email đều đi qua `risky_action -> approval`; nếu không được duyệt thì graph chuyển sang `clarify` thay vì thực thi side effect.

## 6. Persistence / recovery evidence

Project hỗ trợ `MemorySaver` mặc định và `SqliteSaver` khi chọn `checkpointer=sqlite`. Mỗi scenario có `thread_id` riêng dạng `thread-{scenario_id}` nên checkpoint và state history tách biệt theo từng lượt chạy.

## 7. Extension work

Đã bổ sung SQLite checkpointer với cấu hình WAL mode để hỗ trợ persistence bền vững hơn.

## 8. Improvement plan

Nếu có thêm một ngày, tôi sẽ tăng chất lượng prompt cho classification/evaluation, thêm integration test cho resume từ SQLite checkpoint, và thay mock tool bằng tool thật có schema dữ liệu chuẩn.

## 9. Metrics summary

- Total scenarios: 7
- Success rate: 100.00%
- Average nodes visited: 6.43
- Total retries: 3
- Total interrupts: 2