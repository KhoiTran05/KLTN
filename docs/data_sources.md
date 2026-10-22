# Nguồn dữ liệu — Hệ thống Logistics Thời gian thực

Danh mục nguồn dữ liệu trong phạm vi khóa luận: hệ thống nào sinh ra dữ liệu, mỗi nguồn được
ingest như thế nào và đầu ra của từng nguồn dùng để làm gì. Bản ghi mẫu của mọi nguồn nằm ở
[data_samples.md](data_samples.md).

## 1. Nguyên tắc thiết kế

1. **Một bộ giả lập toàn cục**. Một bộ giả lập duy nhất quyết định mọi vận đơn
   và ground truth của nó, sau đó phát từng bản ghi qua đúng kênh mà bản ghi thuộc về (ghi DB,
   gọi REST, file CSV, sự kiện Kafka). `shipment_id` nhất quán giữa các nguồn và có thể đo
   precision/recall dựa trên nhãn.
2. **Tách đơn hàng và vận hành.** Đơn hàng được *sinh ra* ở S1/S2/S3. Các nguồn vận hành
   (S4/S5) chỉ *thay đổi trạng thái* của một đơn đã tồn tại. Hệ thống tài chính (S7) *ghi
   nhận tiền* sau một sự kiện vận hành.

## 2. Danh mục nguồn

| # | Nguồn (hệ thống giả lập) | Vai trò | Dữ liệu | Định dạng | Đường ingest |
|---|---|---|---|---|---|
| S1 | OMS — đặt hàng web/app (PostgreSQL) | Gốc đơn hàng + dữ liệu danh mục | `orders`, `merchants`, `pricing_rules`, `sla_config` | Quan hệ | Debezium CDC → Kafka `oms.public.*` | 1, 7, 8, 9 | Ngay |
| S2 | Partner API (sàn TMĐT đẩy đơn) | Gốc đơn hàng | Đơn hàng theo 2 schema riêng của đối tác | JSON lồng nhau qua REST | FastAPI gateway (kiểm tra + báo giá) → Kafka `partner.orders.raw`; bị từ chối → `logistics.orders.dlq` | 1 | Ngay |
| S3 | Nhập đơn hàng loạt (Excel/CSV của shop) | Gốc đơn hàng | Danh sách đơn, header tiếng Việt, địa chỉ tự do | CSV / XLSX | `landing/bulk_orders/` → Airflow sensor → Spark import | 1 | Ngay |
| S4 | Quét mã tại cơ sở (bưu cục / hub) | Thay đổi trạng thái | Sự kiện quét tại các điểm, kể cả chuyển hoàn | JSON (Avro) | Kafka `logistics.tracking.events` | 2, 5, 8 | Ngay |
| S5 | App shipper | Thay đổi trạng thái | Kết quả lấy / giao hàng, cân nặng thực tế, COD đã thu / đã nộp, ... | JSON (Avro) | Kafka `logistics.shipper.events` | 2, 7 | Ngay |
| S7 | Hệ thống tài chính / tính cước | Ghi nhận tiền | Cước chốt / điều chỉnh cước, phí hoàn, trả COD cho shop | JSON (Avro) | Kafka `logistics.financial.events` | 7 | Ngay |
| S9 | Dữ liệu tham chiếu tĩnh | Dimension Tables | Địa giới + ánh xạ hành chính 2025, cơ sở, tuyến, shipper, dịch vụ, chuyển trạng thái, lý do thất bại | CSV / Parquet | Seed một lần lên S3 | 1, 2, 9, 13 | Ngay |
| — | Nhãn ground truth (chỉ dùng để đánh giá) | Đánh giá | Lỗi tiêm, bản ghi trùng, sai cước, thất thoát COD, địa chỉ nhiễu | Parquet | Simulator → `sim_labels/` (schema: [data_samples.md §10](data_samples.md)) | Đánh giá | Ngay |

[//]: # (| S6 | GPS &#40;xe tải + shipper&#41; | Telemetry | Tọa độ gửi về mỗi vài giây | JSON &#40;Avro&#41;, tần suất cao | Kafka `logistics.gps.pings` | 3, 8, thực nghiệm | Sau |)

[//]: # (| S8 | Sao kê ngân hàng &#40;file hằng ngày&#41; | Tiền &#40;bên ngoài&#41; | Giao dịch nộp tiền và chi trả | CSV cột cố định | `landing/bank/` → Airflow → đối soát | 7 | Sau |)

[//]: # (**Nền tảng:** Schema Registry &#40;Avro, tương thích ngược&#41; cho mọi topic Kafka; DataHub cho)

[//]: # (metadata/lineage &#40;Postgres, Kafka, Iceberg, Airflow&#41;; Prometheus cho metric của Kafka /)

[//]: # (Spark / các thành phần ingest; Superset đọc ClickHouse và Athena/Trino.)

## 3. Luồng xử lý

```
 S1 OMS Postgres ──Debezium CDC──► oms.public.orders ──┐
 S2 Partner API ──FastAPI gateway─► partner.orders.raw ─┤  Spark Streaming
                                                        ├─► Chuẩn hóa đơn hàng
 S3 CSV/Excel ──landing/──► Airflow + Spark import ─────┘  (kiểm tra, địa chỉ, khử trùng,
                            (batch, đẩy lại vào Kafka)        kiểm tra cước)
                                                                │
                                      ┌─────────────────────────┤
                                      ▼                         ▼
                          logistics.orders.canonical      logistics.orders.dlq
                                      │
 S4 quét mã / S5 shipper / S7 tài chính ──┤  (vào thẳng Kafka)
                                      ▼
            Streaming job: state machine, KPI, bất thường → ClickHouse → Grafana / Superset
 Mọi topic ──► Bronze (raw, theo nguồn) ──► Silver ──► Gold   (Airflow batch, ground truth)
 Bảng danh mục S1 (CDC) ──► Silver SCD2 (dim_merchant, dim_pricing, dim_sla)
 Tham chiếu S9 ──► các bảng dim
```

| Nguồn | Luồng | Độ trễ | Đầu ra → mục đích |
|---|---|---|---|
| S1 đơn hàng | Ghi OMS → CDC → chuẩn hóa → canonical | giây | Canonical order (kích hoạt state machine); Bronze `oms_orders` (kiểm toán, replay); các `UPDATE` (đổi địa chỉ, hủy) trở thành sự kiện vòng đời |
| S1 danh mục | CDC → Silver SCD2; streaming nạp lại định kỳ (broadcast) | phút | `dim_merchant`, `dim_pricing` (kiểm tra cước, báo cáo theo hợp đồng), `dim_sla` (deadline SLA, cảnh báo nguy cơ trễ) |
| S2 | Đối tác POST → gateway (kiểm tra schema, báo giá) → topic raw → chuẩn hóa (map 2 schema) → canonical | giây | Canonical order; Bronze raw theo đối tác; tỷ lệ lỗi theo đối tác; độ trễ API |
| S3 | File → sensor → Spark import (đọc, báo giá, chuẩn hóa) → canonical + DLQ | 1–5 phút | Canonical order; báo cáo nhập theo file (nhận / từ chối / trùng); Bronze các dòng file gốc |
| S4 | Kafka → state machine, KPI, Bronze | giây | Trạng thái vận đơn, KPI và tồn đọng theo cơ sở, cảnh báo kẹt/mất/sai tuyến, `fact_shipment_route` |
| S5 | Kafka → state machine, luồng COD, Bronze | giây | Lần giao hàng, tỷ lệ giao thành công lần đầu, lý do thất bại, COD đã thu / đã nộp |
| S7 | Kafka → KPI doanh thu, Bronze | giây | Doanh thu realtime, `fact_financial_transaction`, chi trả COD |
| S9 | Seed → các bảng dim | — | Dimension, bảng chuyển trạng thái cho state machine |


## 4. Nguồn gốc các khoản tiền

Mỗi con số tiền chỉ có đúng một nguồn ghi nhận.

| Khoản tiền | Xác định tại | Nguồn | Sự kiện / trường |
|---|---|---|---|
| COD cam kết | Tạo đơn (có thể đổi qua cập nhật OMS trước khi giao) | S1/S2/S3 | `cod_amount_vnd` |
| Giá trị khai báo | Tạo đơn | S1/S2/S3 | `declared_value_vnd` |
| Cước dự kiến (cước chính, xăng dầu, vùng xa, bảo hiểm, phí thu hộ, chiết khấu) | Tạo đơn | S1/S2/S3 (xem §5) | `quote.*` |
| Thời hạn giao cam kết | Tạo đơn | S1/S2/S3 theo `sla_config` | `promised_delivery_at` |
| Cân nặng thực tế | Lấy hàng | S5 | `picked_up.actual_weight_gram` |
| Cước chốt | Sau khi cân lại | S7 | `fee_confirmed` hoặc `fee_adjusted` |
| Phí hoàn | Khi bắt đầu hoàn | S7 | `return_fee_charged` |
| COD thực thu (+ cước nếu người nhận trả) | Giao thành công | S5 | `delivered.cod_collected_vnd`, `fee_collected_vnd` |
| COD nộp về bưu cục | Cuối ca shipper | S5 | `cod_remitted` |
| Đối soát với shop | Theo kỳ đối soát (hằng ngày / hằng tuần) | S7 | `merchant_settlement` (= COD − cước − phí hoàn, mỗi merchant một sự kiện mỗi kỳ) |
| Số tiền ngân hàng ghi nhận | Hằng ngày | S8 (sau) | các dòng sao kê |


## 5. Báo giá và kiểm tra cước

Khách hàng luôn thấy cước dự kiến trước khi xác nhận, nên cước có sẵn ngay tại nguồn:

| Kênh | Ai báo giá | Bản ghi nguồn có cước không? |
|---|---|---|
| S1 OMS | OMS, theo `pricing_rules` trong cùng CSDL | Có, kèm `pricing_version` |
| S2 Partner API | Gateway, trả về trong response của API | Payload đối tác: không. Bản ghi ghi vào Kafka: có |
| S3 CSV | Job import (đóng vai cổng upload) | File gốc: không. Bản ghi sau import: có |

`pricing_rules` (OMS) là bảng giá duy nhất; bảng này được CDC sang `dim_pricing` (SCD2) và mọi
kênh đều đọc cùng một bộ quy tắc.

Bước chuẩn hóa **giữ nguyên cước từ nguồn** (con số khách đã đồng ý) và tính lại theo phiên
bản `dim_pricing` có hiệu lực tại `created_at`. Nếu lệch thì gắn `FEE_MISMATCH` kèm cả hai giá
trị và độ chênh; bản ghi vẫn đi tiếp. Bộ giả lập tiêm các lỗi cước có gắn nhãn (sai phiên bản
bảng giá, thiếu phụ phí vùng xa, sai phí bảo hiểm) để đo khả năng phát hiện.

## 6. Các vấn đề giữa các nguồn được xử lý phía sau

- **Quét mã trước khi có đơn.** Sự kiện quét có thể đến cho một `shipment_id` mà đơn vẫn đang
  nằm trong lô CSV hoặc trong DLQ. State machine giữ tạm sự kiện; hết thời gian chờ thì phát
  `ORPHAN_EVENT`.
- **Một đơn gửi qua hai kênh.** Shop vừa upload CSV vừa đẩy qua API. Khử trùng theo `event_id`
  không bắt được; khóa nghiệp vụ `(merchant_id, merchant_order_ref)` thì bắt được.
