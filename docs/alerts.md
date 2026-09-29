# Alert và runbook

Mỗi alert phải dựa trên triệu chứng người dùng hoặc SLO, không dựa trực tiếp vào tên implementation nội bộ.

## Alert 1

- Tên: `HighRequestLatency`
- Severity: warning
- Duration: 5 phút
- Kênh thông báo: Slack `#llmops-alerts`
- SLI/SLO liên quan: tỷ lệ request thành công có `latency_ms <= 3000`.
- Điều kiện và thời gian duy trì: P95 latency lớn hơn 3,000 ms liên tục 5 phút.
- Ảnh hưởng tới người dùng: câu trả lời chậm, có nguy cơ timeout ở client.
- Ba bước kiểm tra đầu tiên:
  1. Mở panel Latency, xác định thời điểm P95/TTFT bắt đầu tăng.
  2. Lọc `response_sent` chậm, lấy `correlation_id` và kiểm tra log lỗi cùng khoảng thời gian.
  3. Mở trace cùng ID, so sánh thời lượng observation `retrieval` và `fake-llm-generation`.
- Mitigation tạm thời: giảm concurrency hoặc tạm chuyển traffic khỏi dependency/span đang chậm; rollback prompt nếu generation phình to sau thay đổi prompt.
- Owner: `platform-oncall`

## Alert 2

- Tên: `ElevatedRequestErrorRate`
- Severity: critical
- Duration: 5 phút
- Kênh thông báo: Slack `#llmops-alerts`
- SLI/SLO liên quan: error rate tối đa 2% và retrieval success tối thiểu 90%.
- Điều kiện và thời gian duy trì: `request_failed / request_received > 2%` liên tục 5 phút.
- Ảnh hưởng tới người dùng: request trả HTTP 500 hoặc không có câu trả lời.
- Ba bước kiểm tra đầu tiên:
  1. Mở panel Errors, xem breakdown `error_type` và retrieval success.
  2. Lọc một `request_failed`, lấy `correlation_id`, `tool_name` và `tool_success`.
  3. Mở trace cùng ID để xác định observation đầu tiên báo lỗi.
- Mitigation tạm thời: vô hiệu dependency lỗi, dùng fallback retrieval/answer an toàn hoặc rollback release vừa triển khai.
- Owner: `api-oncall`

## Alert 3

- Tên: `QualityScoreDegraded`
- Severity: warning
- Duration: 15 phút
- Kênh thông báo: Slack `#llmops-alerts`
- SLI/SLO liên quan: quality proxy trung bình tối thiểu 0.75.
- Điều kiện và thời gian duy trì: quality score trung bình nhỏ hơn 0.75 liên tục 15 phút.
- Ảnh hưởng tới người dùng: câu trả lời ít liên quan hoặc không sử dụng đúng context retrieval.
- Ba bước kiểm tra đầu tiên:
  1. So sánh panel Quality theo feature và thời điểm prompt/model thay đổi.
  2. Lấy một request chất lượng thấp và nối log với trace bằng `correlation_id`.
  3. Kiểm tra prompt name/version/label, số document và token trong generation.
- Mitigation tạm thời: rollback label `production` về prompt baseline đã xác minh và theo dõi lại cùng workload.
- Owner: `llm-oncall`
