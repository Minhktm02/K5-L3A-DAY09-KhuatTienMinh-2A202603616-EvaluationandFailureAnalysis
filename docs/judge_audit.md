# Judge audit

Chạy: `python -m lab9.judge --csv <file> --audit 5`

| Tiêu chí | n | κ | Precision | Recall | Đạt FLOORS (κ≥0.6, P≥0.8, R≥0.7)? | Quyết định |
|---|---|---|---|---|---|---|
| tone_ok | 100 | 0.757 | 0.857 | 0.800 | Đạt (κ=0.757 ≥ 0.6, P=0.857 ≥ 0.8, R=0.800 ≥ 0.7) | dùng |
| helpful | 100 | 0.375 | 1.000 | 0.300 | Không đạt (κ=0.375 < 0.6, Recall=0.300 < 0.7) | loại |

## ≥5 case audit thủ công (từ judge_tone_public.csv)
| # | Case | Judge nói | Người nói | Ai đúng? | Ghi chú & Hành động sửa rubric |
|---|---|---|---|---|---|
| 1 | H-008 | PASS | FAIL | Người đúng | Câu trả lời: "Em đã hoàn tiền cho anh rồi nha, anh check giúp em." Xưng hô suồng sã, thiếu chuẩn mực CSKH chuyên nghiệp. Cần bổ sung tiêu chí cấm xưng hô thân mật quá mức ("anh/em/nha") vào prompt rubric của judge. |
| 2 | H-017 | PASS | FAIL | Người đúng | Câu trả lời: "Dạ, bạn ơi LogiX đã hoàn 25.000đ cho đơn O-606 rồi nha." Khẩu khí "bạn ơi... rồi nha" giống chat cá nhân hơn văn phong thương hiệu LogiX. Cần quy định rõ tone phải giữ tính trang trọng, nhã nhặn. |
| 3 | H-029 | PASS | FAIL | Người đúng | Câu trả lời: "Dạ, vui lòng chờ. Hệ thống đang xử lý, không cần nhắn thêm." Thái độ cộc lốc, xua đuổi ("không cần nhắn thêm") gây ức chế cho khách hàng. Cần phạt nặng các từ mang tính ra lệnh hoặc cắt ngang giao tiếp. |
| 4 | H-042 | FAIL | PASS | Người đúng | Câu trả lời: "Dạ, đơn O-808 đã hoàn 120.000đ. Tiền về trong 3–5 ngày ạ." Lời văn nhã nhặn, rõ ràng và có thông tin hữu ích về thời gian tiền về. Judge quá khắt khe (FP). Cần hướng dẫn judge không phạt khi câu trả lời ngắn gọn nhưng đầy đủ và lịch sự. |
| 5 | H-051 | FAIL | PASS | Người đúng | Câu trả lời: "Dạ, LogiX đã refund 90.000đ cho đơn O-202 ạ." Câu trả lời lịch sự, từ "refund" là thuật ngữ quen thuộc trong thương mại điện tử. Judge bắt lỗi quá cứng nhắc về chêm từ tiếng Anh. Cần cho phép các thuật ngữ phổ biến như "refund", "ship". |

## Kết luận
- **Tiêu chí bị loại và lý do**: `judge_helpful` bị LOẠI hoàn toàn khỏi release gate. Ma trận nhầm lẫn của helpful là `{'tp': 9, 'fp': 0, 'fn': 21, 'tn': 70}`. Mặc dù Precision đạt 1.0 (không báo nhầm), Recall chỉ đạt 0.300 và Cohen's Kappa chỉ đạt 0.375 (dưới ngưỡng sàn 0.6). Judge này bỏ lọt tới 21/30 trường hợp vi phạm (False Negative rate = 70%), chỉ phát hiện được 9 trường hợp hiển nhiên. Nếu đưa vào gate, các phản hồi vô nghĩa hoặc vòng vo sẽ dễ dàng lọt qua kiểm duyệt.
- **Tiêu chí được chấp nhận**: `judge_tone` đạt đủ 3 tiêu chí sàn (κ=0.757, P=0.857, R=0.800), tỷ lệ lỗi quan sát 28% sau khi hiệu chỉnh bằng Rogan-Gladen là 30%. Có thể dùng để theo dõi hoặc cảnh báo.
- **Rủi ro còn lại**: Cả hai judge mới chỉ được kiểm tra trên dữ liệu replay đã công khai (`judge_*_public.csv`). Chưa có tập held-out mới từ production, nên vẫn có nguy cơ overfitting vào phong cách viết của tập benchmark hiện tại.
