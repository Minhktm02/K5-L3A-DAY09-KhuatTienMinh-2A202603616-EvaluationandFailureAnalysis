# Trace case: từ trace tới quyết định sai đầu tiên

Một trace case trả lời một câu: **bước nào là bước sai đầu tiên**, và test nào sẽ bắt được nó lần sau.

```bash
cd src
python -m lab9.trace_case --shape seeded_regression --claim C-002 --seed 11
python -m lab9.trace_case --shape fixed --claim C-002 --seed 11   # đối chứng
```

Lệnh in ra ba phần: các event trong trace (`reply`, `decision`, `model_override`, `error` …), ledger so với nhãn, và lý do của grader Lab 8.

## Mẫu điền (Case C-002@11 trên shape seeded_regression)

| Trường | Nội dung |
|---|---|
| Trial | `seeded_regression C-002@11`, run ID: `E-seeded_regression-20261117-c226` |
| Triệu chứng | Grader Lab 8 fail: `status resolved != denied`. Ledger ghi nhận hoàn 20.000đ (`refund_vnd=20000`, `refund_count=1`), trong khi nhãn kỳ vọng từ chối (`status=denied`, `refund_vnd=0`, `refund_count=0`). Reply phát ngôn: "Dạ, LogiX đã hoàn 20.000đ cho đơn O-202." |
| Bước sai đầu tiên | Event #3 — `model_override` — `{"delay_days": 5}` |
| Vì sao là bước *đầu tiên* | Các event trước đó (#1 `handoff`, #2 `investigator`) hoàn toàn chính xác: DB trả về đơn O-202 giao trễ 2 ngày (`delay_days: 2`). Đến event #3, agent tin lời ticket của khách (kêu trễ 5 ngày) và phát sinh event `model_override` đè số 5 lên DB. Dẫn tới bước #4 tính bồi thường ra 20.000đ. |
| Failure mode | `FM-03` (`ticket_trust — tin ticket hơn DB`) |
| Đối chứng | Cùng claim@seed trên shape `fixed`: Không có event `model_override`. Event #3 nhận diện đúng số ngày trễ từ DB là 2 ngày (< 3 ngày theo chính sách), trả về `quote {"amount_vnd": 0, "reason": "no_entitlement"}`, từ chối hoàn tiền hợp lệ. |
| Regression test | Grader `DbFactKept` kiểm tra không có event `model_override`; grader `RefundAmountCorrect` kiểm tra số tiền hoàn = 0đ; test `test_override_event_breaks_db_fact` trong `src/tests/test_lab9_graders.py`. Đã xác nhận FAIL trên `seeded_regression` và PASS trên `fixed`. |
| Chưa chắc chắn | Trace ghi lại sự kiện override nhưng không phản ánh chuỗi suy luận nội tâm (chain of thought) chi tiết của LLM thật do đang chạy giả lập với MockLLM. |

## Quy tắc

- Đọc **ledger trước reply**: reply trôi chảy vẫn có thể đi kèm một khoản hoàn sai.
- "Bước sai đầu tiên" phải dẫn số event cụ thể, không phải "agent bị nhầm".
- Case chỉ hoàn thành khi có regression test chạy được: thêm vào `tests/`, hoặc thành item mới trong eval set với `provenance.from_trace`.
