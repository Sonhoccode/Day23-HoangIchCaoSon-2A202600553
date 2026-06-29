"""Report generation helper.

TODO(student): implement report rendering using MetricsReport data
and the template in reports/lab_report_template.md.
"""

from __future__ import annotations

from pathlib import Path

from .metrics import MetricsReport


def render_report(metrics: MetricsReport) -> str:
    """Render a complete lab report from metrics data.

    TODO(student): Generate a report that includes:
    1. Metrics summary table (total scenarios, success rate, retries, interrupts)
    2. Per-scenario results table
    3. Architecture explanation (your graph design, state schema, reducers)
    4. Failure analysis (at least two failure modes you considered)
    5. Improvement plan

    Use reports/lab_report_template.md as your guide.

    Return: formatted markdown string
    """
    rows = [
        "| Scenario | Expected route | Actual route | Success | Retries | Interrupts |",
        "|---|---|---|---:|---:|---:|",
    ]
    for item in metrics.scenario_metrics:
        rows.append(
            f"| {item.scenario_id} | {item.expected_route} | {item.actual_route or '-'} | "
            f"{'yes' if item.success else 'no'} | {item.retry_count} | {item.interrupt_count} |"
        )

    return "\n".join(
        [
            "# Day 08 Lab Report",
            "",
            "## 1. Team / student",
            "",
            "- Name: Hoang Ich Cao Son",
            "- Repo/commit: local workspace",
            "- Date: 2026-06-29",
            "",
            "## 2. Architecture",
            "",
            (
                "Graph sử dụng `StateGraph` với các node `intake`, `classify`, `tool`, "
                "`evaluate`, `answer`, `clarify`, `risky_action`, `approval`, `retry`, "
                "`dead_letter`, `finalize`. `classify` quyết định route bằng LLM, sau đó "
                "các conditional edge điều phối nhánh `simple`, `tool`, `missing_info`, "
                "`risky`, `error` và đảm bảo mọi đường đi đều kết thúc tại `finalize -> END`."
            ),
            "",
            "## 3. State schema",
            "",
            "| Field | Reducer | Why |",
            "|---|---|---|",
            "| messages | append | lưu log ngắn theo từng bước |",
            "| tool_results | append | giữ lịch sử kết quả tool, gồm cả retry |",
            "| errors | append | theo dõi lỗi transient và lỗi cuối cùng |",
            "| events | append | audit trail cho grading và debug |",
            "| route | overwrite | chỉ có một route hiện hành |",
            "| evaluation_result | overwrite | điều khiển retry loop sau evaluate |",
            "| pending_question | overwrite | câu hỏi clarify cuối cùng |",
            "| proposed_action | overwrite | mô tả hành động rủi ro trước approval |",
            "| approval | overwrite | quyết định HITL gần nhất |",
            "",
            "## 4. Scenario results",
            "",
            *rows,
            "",
            "## 5. Failure analysis",
            "",
            (
                "1. Retry or tool failure: khi tool trả về lỗi, `evaluate` đặt "
                "`evaluation_result=needs_retry` để chuyển sang `retry`; `retry` tăng "
                "`attempt` và route bị chặn bởi `max_attempts` để tránh loop vô hạn."
            ),
            (
                "2. Risky action without approval: các yêu cầu refund, delete, send email "
                "đều đi qua `risky_action -> approval`; nếu không được duyệt thì graph "
                "chuyển sang `clarify` thay vì thực thi side effect."
            ),
            "",
            "## 6. Persistence / recovery evidence",
            "",
            (
                "Project hỗ trợ `MemorySaver` mặc định và `SqliteSaver` khi chọn "
                "`checkpointer=sqlite`. Mỗi scenario có `thread_id` riêng dạng "
                "`thread-{scenario_id}` nên checkpoint và state history tách biệt "
                "theo từng lượt chạy."
            ),
            "",
            "## 7. Extension work",
            "",
            (
                "Đã bổ sung SQLite checkpointer với cấu hình WAL mode để hỗ trợ "
                "persistence bền vững hơn."
            ),
            "",
            "## 8. Improvement plan",
            "",
            (
                "Nếu có thêm một ngày, tôi sẽ tăng chất lượng prompt cho "
                "classification/evaluation, thêm integration test cho resume từ "
                "SQLite checkpoint, và thay mock tool bằng tool thật có schema dữ liệu chuẩn."
            ),
            "",
            "## 9. Metrics summary",
            "",
            f"- Total scenarios: {metrics.total_scenarios}",
            f"- Success rate: {metrics.success_rate:.2%}",
            f"- Average nodes visited: {metrics.avg_nodes_visited:.2f}",
            f"- Total retries: {metrics.total_retries}",
            f"- Total interrupts: {metrics.total_interrupts}",
        ]
    )


def write_report(metrics: MetricsReport, output_path: str | Path) -> None:
    """Write the rendered report to a file."""
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    report_text = render_report(metrics)
    path.write_text(report_text, encoding="utf-8")
