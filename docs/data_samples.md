# Dữ liệu mẫu — theo từng nguồn

Bản ghi mẫu cho mọi nguồn trong [data_sources.md](data_sources.md). Các trường vẫn có thể được
thêm / sửa / xóa khi viết truy vấn KPI và báo cáo trên dữ liệu này.

**Ví dụ xuyên suốt.** §1–§7 lần theo một vận đơn từ đầu đến cuối, `VTP26101800001238`:
shop ở Hà Nội, dịch vụ EXPRESS đi TP.HCM, COD 450.000. Đơn được cân lại khi lấy hàng (điều
chỉnh cước), người nhận đổi số điện thoại, giao lần đầu thất bại (thiết bị mất mạng nên sự
kiện đến trễ), giao lần hai thành công nhưng sau thời hạn cam kết (vi phạm SLA), COD được nộp
về bưu cục và chi trả cho shop.

| Thời gian nghiệp vụ | Nguồn | Sự kiện |
|---|---|---|
| 18/10 09:12 | S1 | Tạo đơn trên OMS (báo giá 59.000) |
| 18/10 09:14 | S5 | Giao nhiệm vụ lấy hàng |
| 18/10 10:41 | S5 | Đã lấy hàng, cân thực tế 2.100 g |
| 18/10 10:41 | S7 | Điều chỉnh cước 59.000 → 75.000 |
| 18/10 11:35 → 19:45 | S4 | Vào/ra bưu cục gốc, vào/chia/ra hub gốc |
| 19/10 08:30 | S1 | Cập nhật SĐT người nhận |
| 19/10 15:30 → 22:40 | S4 | Vào/chia/ra hub đích, vào bưu cục đích |
| 20/10 07:55 | S4 | Xuất giao, lần 1 |
| 20/10 10:05 | S5 | Giao thất bại (đến lúc 14:12, thiết bị mất mạng) |
| 20/10 23:12 | — | Quá thời hạn giao cam kết |
| 21/10 08:02 | S4 | Xuất giao, lần 2 |
| 21/10 09:20 | S5 | Giao thành công, thu COD 450.000 |
| 21/10 18:05 | S5 | Nộp COD cuối ca |
| 22/10 02:00 | S7 | Chi trả COD cho shop: 375.000 |

---

## 1. S1 — OMS (PostgreSQL, CDC)

### 1.1 Các bảng

```sql
CREATE TABLE merchants (
    merchant_id          VARCHAR(16) PRIMARY KEY,      -- MER_000845
    merchant_name        TEXT NOT NULL,
    merchant_type        VARCHAR(16) NOT NULL,         -- INDIVIDUAL / SME / ENTERPRISE
    phone                VARCHAR(16),
    email                TEXT,
    pickup_address       TEXT NOT NULL,                -- văn bản tự do, như khách nhập
    pickup_province_id   VARCHAR(8),
    pickup_district_id   VARCHAR(16),
    pickup_ward_id       VARCHAR(24),
    default_facility_id  VARCHAR(16),                  -- bưu cục phụ trách lấy hàng
    contract_type        VARCHAR(16) NOT NULL,         -- PAY_PER_USE / VOLUME / FIXED
    discount_pct         NUMERIC(5,4) NOT NULL DEFAULT 0, -- chiết khấu trên cước chính
    payout_cycle         VARCHAR(8) NOT NULL,          -- DAILY / WEEKLY
    bank_account_no      VARCHAR(32),
    status               VARCHAR(16) NOT NULL,         -- ACTIVE / SUSPENDED
    created_at           TIMESTAMPTZ NOT NULL,
    updated_at           TIMESTAMPTZ NOT NULL
);

CREATE TABLE pricing_rules (
    rule_id                 SERIAL PRIMARY KEY,
    pricing_version         VARCHAR(16) NOT NULL,     -- PV2026_10
    service_type_id         VARCHAR(16) NOT NULL,
    zone_type               VARCHAR(16) NOT NULL,     -- INNER_CITY / SAME_PROVINCE / INTER_PROVINCE / REMOTE
    first_weight_gram       INT NOT NULL,
    first_weight_fee        BIGINT NOT NULL,
    step_gram               INT NOT NULL,
    step_fee                BIGINT NOT NULL,
    volumetric_divisor      INT NOT NULL,             -- cm3 trên 1 kg
    fuel_surcharge_pct      NUMERIC(5,4) NOT NULL,
    remote_area_fee         BIGINT NOT NULL,
    insurance_pct           NUMERIC(5,4) NOT NULL,
    insurance_threshold     BIGINT NOT NULL,          -- chỉ tính bảo hiểm khi giá trị khai báo vượt ngưỡng này
    cod_fee_pct             NUMERIC(5,4) NOT NULL,
    cod_fee_min             BIGINT NOT NULL,
    return_fee_pct          NUMERIC(5,4) NOT NULL,    -- theo % cước chính
    effective_from          TIMESTAMPTZ NOT NULL,
    effective_to            TIMESTAMPTZ               -- NULL = đang hiệu lực
);

CREATE TABLE sla_config (
    service_type_id     VARCHAR(16),
    zone_type           VARCHAR(16),
    total_hours         INT NOT NULL,      -- tạo đơn → giao thành công
    pickup_hours        INT NOT NULL,      -- tạo đơn → lấy hàng
    first_mile_hours    INT NOT NULL,      -- lấy hàng → rời hub gốc
    linehaul_hours      INT NOT NULL,      -- rời hub gốc → đến hub đích
    last_mile_hours     INT NOT NULL,      -- đến hub đích → giao thành công
    cutoff_time         TIME NOT NULL,     -- đơn sau giờ chốt tính từ ngày hôm sau
    PRIMARY KEY (service_type_id, zone_type)
);

CREATE TABLE orders (
    shipment_id            VARCHAR(20) PRIMARY KEY,   -- mã vận đơn, do OMS sinh
    merchant_id            VARCHAR(16) NOT NULL REFERENCES merchants,
    merchant_order_ref     VARCHAR(64),               -- mã đơn riêng của shop (khử trùng giữa các kênh)
    source_channel         VARCHAR(16) NOT NULL,      -- OMS_WEB / OMS_APP
    service_type_id        VARCHAR(16) NOT NULL,
    status                 VARCHAR(16) NOT NULL,      -- CREATED / CANCELLED (trạng thái vận hành nằm ở S4/S5)
    -- người gửi
    sender_name            TEXT NOT NULL,
    sender_phone           VARCHAR(16) NOT NULL,
    sender_address         TEXT NOT NULL,
    sender_province_id     VARCHAR(8),
    sender_district_id     VARCHAR(16),
    sender_ward_id         VARCHAR(24),
    pickup_facility_id     VARCHAR(16) NOT NULL,
    -- người nhận
    receiver_name          TEXT NOT NULL,
    receiver_phone         VARCHAR(16) NOT NULL,
    receiver_address       TEXT NOT NULL,
    receiver_province_id   VARCHAR(8),
    receiver_district_id   VARCHAR(16),
    receiver_ward_id       VARCHAR(24),
    delivery_facility_id   VARCHAR(16),
    -- hàng hóa
    item_description       TEXT,
    item_category          VARCHAR(16),
    item_quantity          INT,
    weight_gram            INT NOT NULL,              -- khai báo
    length_cm              INT,
    width_cm               INT,
    height_cm              INT,
    is_fragile             BOOLEAN NOT NULL DEFAULT FALSE,
    declared_value_vnd     BIGINT,
    cod_amount_vnd         BIGINT NOT NULL DEFAULT 0,
    fee_payer              VARCHAR(8) NOT NULL,       -- SENDER / RECEIVER
    -- báo giá (OMS tính khi tạo đơn)
    pricing_version        VARCHAR(16) NOT NULL,
    zone_type              VARCHAR(16) NOT NULL,
    charged_weight_gram    INT NOT NULL,
    main_fee_vnd           BIGINT NOT NULL,
    fuel_surcharge_vnd     BIGINT NOT NULL,
    remote_area_fee_vnd    BIGINT NOT NULL,
    insurance_fee_vnd      BIGINT NOT NULL,
    cod_fee_vnd            BIGINT NOT NULL,
    discount_vnd           BIGINT NOT NULL,
    total_fee_vnd          BIGINT NOT NULL,
    promised_delivery_at   TIMESTAMPTZ NOT NULL,
    -- khác
    pickup_note            TEXT,
    delivery_note          TEXT,
    cancel_reason          VARCHAR(32),
    created_at             TIMESTAMPTZ NOT NULL,
    updated_at             TIMESTAMPTZ NOT NULL
);
```

### 1.2 Dòng dữ liệu mẫu

`merchants`

| merchant_id | merchant_name | merchant_type | pickup_address | pickup_ward_id | default_facility_id | contract_type | discount_pct | payout_cycle | status |
|---|---|---|---|---|---|---|---|---|---|
| MER_000845 | Shop Mỹ Phẩm Hoa Mai | SME | Số 12 ngõ 45 phố Huế, Hai Bà Trưng, Hà Nội | P01_D05_W03 | BC_P01_0007 | VOLUME | 0.1000 | DAILY | ACTIVE |
| MER_001203 | Gia Dụng Minh Tâm (Shopee) | SME | 88 Lê Văn Việt, TP. Thủ Đức, TP.HCM | P79_D09_W02 | BC_P79_0110 | PAY_PER_USE | 0.0000 | DAILY | ACTIVE |
| MER_002210 | Thời Trang Linh Chi | INDIVIDUAL | 25 Trần Phú, Hải Châu, Đà Nẵng | P48_D01_W05 | BC_P48_0003 | PAY_PER_USE | 0.0000 | WEEKLY | ACTIVE |

`pricing_rules` (hai phiên bản → SCD2 trong `dim_pricing`)

| rule_id | pricing_version | service_type_id | zone_type | first_weight_gram | first_weight_fee | step_gram | step_fee | volumetric_divisor | fuel_surcharge_pct | remote_area_fee | insurance_pct | insurance_threshold | cod_fee_pct | cod_fee_min | return_fee_pct | effective_from | effective_to |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 101 | PV2026_07 | EXPRESS | INTER_PROVINCE | 500 | 36000 | 500 | 7500 | 6000 | 0.0800 | 15000 | 0.0050 | 1000000 | 0.0100 | 5000 | 0.5000 | 2026-07-01 00:00+07 | 2026-10-01 00:00+07 |
| 245 | PV2026_10 | EXPRESS | INTER_PROVINCE | 500 | 38000 | 500 | 8000 | 6000 | 0.1000 | 15000 | 0.0050 | 1000000 | 0.0100 | 5000 | 0.5000 | 2026-10-01 00:00+07 | NULL |
| 246 | PV2026_10 | STANDARD | INTER_PROVINCE | 500 | 25000 | 500 | 5000 | 6000 | 0.1000 | 15000 | 0.0050 | 1000000 | 0.0100 | 5000 | 0.5000 | 2026-10-01 00:00+07 | NULL |
| 247 | PV2026_10 | EXPRESS | INNER_CITY | 500 | 22000 | 500 | 5000 | 6000 | 0.1000 | 15000 | 0.0050 | 1000000 | 0.0100 | 5000 | 0.5000 | 2026-10-01 00:00+07 | NULL |

`sla_config`

| service_type_id | zone_type | total_hours | pickup_hours | first_mile_hours | linehaul_hours | last_mile_hours | cutoff_time |
|---|---|---|---|---|---|---|---|
| EXPRESS | INTER_PROVINCE | 62 | 4 | 10 | 30 | 18 | 17:00 |
| EXPRESS | INNER_CITY | 24 | 3 | 4 | 4 | 13 | 17:00 |
| STANDARD | INTER_PROVINCE | 110 | 8 | 14 | 60 | 28 | 16:00 |

`orders` — ví dụ xuyên suốt (báo giá do OMS tính)

| cột | giá trị |
|---|---|
| shipment_id | VTP26101800001238 |
| merchant_id / merchant_order_ref | MER_000845 / HM-20261018-0311 |
| source_channel / service_type_id / status | OMS_WEB / EXPRESS / CREATED |
| người gửi | Shop Mỹ Phẩm Hoa Mai · 0987654321 · Số 12 ngõ 45 phố Huế, Hai Bà Trưng, Hà Nội · P01 / P01_D05 / P01_D05_W03 |
| pickup_facility_id | BC_P01_0007 |
| người nhận | Nguyễn Thị Lan · 0912345678 · 102 Nguyễn Huệ, Phường Bến Nghé, Quận 1, TP.HCM · P79 / P79_D01 / P79_D01_W04 |
| delivery_facility_id | BC_P79_0042 |
| hàng hóa | "Bộ dưỡng da 3 món" · COSMETICS · SL 3 · 1.200 g · 30×20×15 cm · dễ vỡ = true |
| declared_value_vnd / cod_amount_vnd / fee_payer | 450.000 / 450.000 / SENDER |
| pricing_version / zone_type / charged_weight_gram | PV2026_10 / INTER_PROVINCE / 1.500 (quy đổi 30·20·15/6000 = 1,5 kg > 1,2 kg) |
| main_fee_vnd | 54.000 (38.000 + 2 × 8.000) |
| xăng dầu / vùng xa / bảo hiểm / phí thu hộ / chiết khấu | 5.400 / 0 / 0 (dưới 1.000.000) / 5.000 (max(1% × 450.000, 5.000)) / 5.400 (10% cước chính) |
| total_fee_vnd | 59.000 |
| promised_delivery_at | 2026-10-20 23:12:05+07 (tạo đơn + 62 giờ) |
| delivery_note | Giao giờ hành chính |
| created_at / updated_at | 2026-10-18 09:12:05+07 / 2026-10-18 09:12:05+07 |

### 1.3 Bản ghi CDC (Debezium → Kafka `oms.public.orders`)

INSERT (`op = "c"`), `after` đã rút gọn:

```json
{
  "before": null,
  "after": {
    "shipment_id": "VTP26101800001238", "merchant_id": "MER_000845",
    "merchant_order_ref": "HM-20261018-0311", "source_channel": "OMS_WEB",
    "service_type_id": "EXPRESS", "status": "CREATED",
    "sender_name": "Shop Mỹ Phẩm Hoa Mai", "sender_phone": "0987654321",
    "sender_address": "Số 12 ngõ 45 phố Huế, Hai Bà Trưng, Hà Nội",
    "sender_province_id": "P01", "sender_district_id": "P01_D05", "sender_ward_id": "P01_D05_W03",
    "pickup_facility_id": "BC_P01_0007",
    "receiver_name": "Nguyễn Thị Lan", "receiver_phone": "0912345678",
    "receiver_address": "102 Nguyễn Huệ, Phường Bến Nghé, Quận 1, TP.HCM",
    "receiver_province_id": "P79", "receiver_district_id": "P79_D01", "receiver_ward_id": "P79_D01_W04",
    "delivery_facility_id": "BC_P79_0042",
    "item_description": "Bộ dưỡng da 3 món", "item_category": "COSMETICS", "item_quantity": 3,
    "weight_gram": 1200, "length_cm": 30, "width_cm": 20, "height_cm": 15, "is_fragile": true,
    "declared_value_vnd": 450000, "cod_amount_vnd": 450000, "fee_payer": "SENDER",
    "pricing_version": "PV2026_10", "zone_type": "INTER_PROVINCE", "charged_weight_gram": 1500,
    "main_fee_vnd": 54000, "fuel_surcharge_vnd": 5400, "remote_area_fee_vnd": 0,
    "insurance_fee_vnd": 0, "cod_fee_vnd": 5000, "discount_vnd": 5400, "total_fee_vnd": 59000,
    "promised_delivery_at": "2026-10-20T16:12:05Z",
    "pickup_note": null, "delivery_note": "Giao giờ hành chính", "cancel_reason": null,
    "created_at": "2026-10-18T02:12:05Z", "updated_at": "2026-10-18T02:12:05Z"
  },
  "source": {
    "connector": "postgresql", "name": "oms", "db": "oms", "schema": "public",
    "table": "orders", "lsn": 23849120, "txId": 77812, "ts_ms": 1792289525112
  },
  "op": "c",
  "ts_ms": 1792289525380
}
```

UPDATE — shop đổi SĐT người nhận (`op = "u"`, chỉ hiển thị các cột thay đổi):

```json
{
  "before": { "shipment_id": "VTP26101800001238", "receiver_phone": "0912345678",
              "updated_at": "2026-10-18T02:12:05Z" },
  "after":  { "shipment_id": "VTP26101800001238", "receiver_phone": "0938112233",
              "updated_at": "2026-10-19T01:30:00Z" },
  "source": { "table": "orders", "lsn": 24115508, "ts_ms": 1792373400051 },
  "op": "u",
  "ts_ms": 1792373400270
}
```

---

## 2. S2 — Partner API

Hai đối tác, hai schema không tương thích. Gateway cấp mã vận đơn, báo giá cước và phản hồi
đồng bộ.

### 2.1 Request kiểu Shopee (`POST /v1/partners/shopee/orders`)

```json
{
  "order_sn": "251018ABCD1234",
  "shop": { "shop_id": 88123, "merchant_code": "MER_001203" },
  "create_time": 1792292523,
  "service_code": "EXP",
  "pickup": {
    "name": "Gia Dụng Minh Tâm", "phone": "+84 909 111 222",
    "full_address": "88 Lê Văn Việt, P. Hiệp Phú, TP. Thủ Đức, TP.HCM"
  },
  "recipient": {
    "name": "Trần Văn Hùng", "phone": "0905 333 444",
    "full_address": "15 Nguyễn Văn Linh, P. Nam Dương, Q. Hải Châu, Đà Nẵng",
    "city": "Đà Nẵng", "district": "Hải Châu", "ward": "Nam Dương"
  },
  "parcel": {
    "weight_kg": 0.8, "dimension_cm": { "l": 25, "w": 18, "h": 10 },
    "items": [ { "name": "Nồi chiên không dầu mini", "qty": 1, "price": 289000 } ]
  },
  "cod_amount": 289000,
  "item_value": 289000,
  "fee_paid_by": "buyer",
  "remark": "Gọi trước khi giao"
}
```

### 2.2 Request kiểu TikTok Shop (`POST /v1/partners/tiktok/orders`)

```json
{
  "orderId": "577301928374651",
  "sellerId": "MER_000845",
  "createdAt": "2026-10-18T03:15:40Z",
  "shippingService": "STANDARD",
  "sender":   { "contactName": "Shop Mỹ Phẩm Hoa Mai", "contactPhone": "0987654321",
                "address": { "line1": "Số 12 ngõ 45 phố Huế", "district": "Hai Bà Trưng", "province": "Hà Nội" } },
  "receiver": { "contactName": "Lê Thu Hà", "contactPhone": "0977000111",
                "address": { "line1": "Thôn 3", "ward": "Xã Nậm Ty", "district": "Huyện Hoàng Su Phì", "province": "Hà Giang" } },
  "package":  { "weightGram": "650", "lengthCm": 20, "widthCm": 15, "heightCm": 8 },
  "items":    [ { "skuName": "Son dưỡng môi", "quantity": 2, "unitPrice": { "amount": "175000", "currency": "VND" } } ],
  "codAmount":     { "amount": "350000", "currency": "VND" },
  "declaredValue": { "amount": "350000", "currency": "VND" },
  "payer": "SELLER"
}
```

### 2.3 Response của gateway (đơn Shopee)

```json
{
  "tracking_number": "VTP26101800001246",
  "status": "ACCEPTED",
  "quote": {
    "pricing_version": "PV2026_10", "zone_type": "INTER_PROVINCE", "charged_weight_gram": 800,
    "main_fee_vnd": 46000, "fuel_surcharge_vnd": 4600, "remote_area_fee_vnd": 0,
    "insurance_fee_vnd": 0, "cod_fee_vnd": 5000, "discount_vnd": 0, "total_fee_vnd": 55600
  },
  "promised_delivery_at": "2026-10-21T00:02:03+07:00"
}
```

Request bị từ chối (thiếu SĐT người nhận) → `400`:

```json
{ "status": "REJECTED", "errors": [ { "field": "recipient.phone", "code": "REQUIRED" } ],
  "request_id": "req_7f3a9c01" }
```

Đồng thời gateway ghi một bản ghi vào `logistics.orders.dlq` (cùng cấu trúc §4, `stage = "GATEWAY"`;
không cấp mã vận đơn):

```json
{
  "dlq_id": "a83c19e4-…", "failed_at": "2026-10-18T10:05:51+07:00",
  "source_channel": "PARTNER_API", "source_ref": "shopee:req_7f3a9c01",
  "stage": "GATEWAY", "errors": ["recipient.phone:REQUIRED"],
  "raw": { "...": "body request gốc" }
}
```

### 2.4 Bản ghi gateway ghi vào Kafka `partner.orders.raw`

```json
{
  "event_id": "4b6f8e1c-2a0d-4f5e-9b77-1d2c3e4f5a60",
  "event_type": "partner_order_received",
  "event_time": "2026-10-18T10:02:03+07:00",
  "processing_time": "2026-10-18T10:02:03.412+07:00",
  "schema_version": "v2.0",
  "shipment_id": "VTP26101800001246",
  "source_system": "PARTNER_API",
  "partner_id": "SHOPEE",
  "partner_schema": "shopee.v1",
  "partner_order_ref": "251018ABCD1234",
  "merchant_id": "MER_001203",
  "request_id": "req_7f3a9b22",
  "quote": { "...": "giống trong response" },
  "promised_delivery_at": "2026-10-21T00:02:03+07:00",
  "payload": { "...": "body request gốc, giữ nguyên" }
}
```

---

## 3. S3 — Nhập đơn hàng loạt (CSV / Excel)

### 3.1 File gốc `landing/bulk_orders/MER_002210/2026-10-18/MER_002210_20261018_1100.csv`

Header tiếng Việt, địa chỉ tự do, có các dòng cố ý chứa lỗi:

```csv
STT,Mã đơn shop,Tên người nhận,SĐT người nhận,Địa chỉ người nhận,Tỉnh/Thành phố,Quận/Huyện,Phường/Xã,Tên hàng,Số lượng,Khối lượng (gram),Dài (cm),Rộng (cm),Cao (cm),Giá trị hàng,Tiền thu hộ (COD),Dịch vụ,Người trả cước,Ghi chú
1,LC-1018-001,Phạm Minh Anh,0934567890,"45 Lý Thường Kiệt, P.Thạch Thang",Đà Nẵng,Hải Châu,Thạch Thang,Áo sơ mi nữ,2,400,25,20,5,320000,320000,Tiết kiệm,Người gửi,
2,LC-1018-002,Hoàng Văn Nam,84 912 000 999,"12 đường 3/2, phường 10, quận 10",TP HCM,Q10,P.10,Váy dự tiệc,1,600,30,25,6,550000,550000,Nhanh,Người nhận,Giao sau 17h
3,LC-1018-003,Đỗ Thị Hà,09123,"Thôn Đông, xã Hòa Tiến",Đà Nẵng,Hòa Vang,,Quần jean,1,500,30,20,5,280000,280000,Tiết kiệm,Người gửi,
4,LC-1018-004,Bùi Quốc Bảo,0977123456,"8 Trần Hưng Đạo",Hà Nội,Hoàn Kiếm,Phan Chu Trinh,Áo khoác,1,-300,35,30,8,700000,700000,Tiết kiệm,Người gửi,
5,LC-1018-005,Ngô Thanh Tâm,0966888777,"200 Hùng Vương",Huế,Thành phố Huế,Phú Nhuận,Khăn lụa,3,300,20,15,3,240000,-240000,Tiết kiệm,Người gửi,
6,LC-1017-088,Võ Thị Mai,0939555666,"77 Hoàng Diệu, Phước Ninh",Đà Nẵng,Hải Châu,Phước Ninh,Đầm maxi,1,500,30,25,5,410000,410000,Tiết kiệm,Người gửi,
```

| Dòng | Vấn đề (tiêm có gắn nhãn) | Kết quả import |
|---|---|---|
| 1 | — | ACCEPTED → `VTP26101800001261` |
| 2 | SĐT `84 912 000 999`, viết tắt `TP HCM` / `Q10` / `P.10`, địa chỉ 3 cấp cũ | ACCEPTED sau chuẩn hóa (SĐT → `0912000999`, địa chỉ khớp) → `VTP26101800001279` |
| 3 | SĐT sai `09123`, thiếu phường/xã | REJECTED `INVALID_PHONE` (thiếu phường/xã → cảnh báo `WARD_UNRESOLVED`) |
| 4 | Cân nặng âm | REJECTED `NON_POSITIVE_WEIGHT` |
| 5 | COD âm | REJECTED `NEGATIVE_COD` |
| 6 | Đơn đã được tạo hôm trước trên app OMS (`MER_002210` / `LC-1017-088`) | REJECTED `CROSS_CHANNEL_DUPLICATE` |

Dòng 6 bị phát hiện nhờ khóa nghiệp vụ `(merchant_id, merchant_order_ref)`, không phải nhờ `event_id`.

### 3.2 Dòng Bronze raw (mỗi dòng CSV một bản ghi, giữ nguyên giá trị + metadata của file)

```json
{
  "file_path": "landing/bulk_orders/MER_002210/2026-10-18/MER_002210_20261018_1100.csv",
  "file_sha256": "9c1e…a7f2", "merchant_id": "MER_002210", "row_no": 2,
  "uploaded_at": "2026-10-18T11:00:12+07:00", "ingested_at": "2026-10-18T11:02:40+07:00",
  "raw": { "STT": "2", "Mã đơn shop": "LC-1018-002", "Tên người nhận": "Hoàng Văn Nam",
           "SĐT người nhận": "84 912 000 999", "Địa chỉ người nhận": "12 đường 3/2, phường 10, quận 10",
           "Tỉnh/Thành phố": "TP HCM", "Quận/Huyện": "Q10", "Phường/Xã": "P.10", "…": "…" }
}
```

### 3.3 Báo cáo import (theo file, ghi lên S3 và trả về cho shop)

```json
{
  "file_path": "landing/bulk_orders/MER_002210/2026-10-18/MER_002210_20261018_1100.csv",
  "merchant_id": "MER_002210", "import_run_id": "imp_20261018_110240_001",
  "total_rows": 6, "accepted": 2, "rejected": 4, "warnings": 2,
  "rows": [
    { "row_no": 1, "status": "ACCEPTED", "shipment_id": "VTP26101800001261", "total_fee_vnd": 26800 },
    { "row_no": 2, "status": "ACCEPTED", "shipment_id": "VTP26101800001279", "total_fee_vnd": 47300,
      "warnings": ["PHONE_NORMALIZED", "ADDRESS_FUZZY_MATCH(score=0.91)"] },
    { "row_no": 3, "status": "REJECTED", "errors": ["INVALID_PHONE"], "warnings": ["WARD_UNRESOLVED"] },
    { "row_no": 4, "status": "REJECTED", "errors": ["NON_POSITIVE_WEIGHT"] },
    { "row_no": 5, "status": "REJECTED", "errors": ["NEGATIVE_COD"] },
    { "row_no": 6, "status": "REJECTED", "errors": ["CROSS_CHANNEL_DUPLICATE"],
      "duplicate_of": "VTP26101700009915" }
  ]
}
```

---

## 4. Đơn hàng chuẩn (`logistics.orders.canonical`)

Hợp đồng dữ liệu duy nhất sau chuẩn hóa, giống nhau dù đến từ kênh nào. Ví dụ xuyên suốt:

```json
{
  "event_id": "0e5c2d7a-6f41-4c1b-8a9e-3b2f1d0c9e88",
  "event_type": "order_created",
  "event_time": "2026-10-18T09:12:05+07:00",
  "processing_time": "2026-10-18T09:12:06.104+07:00",
  "schema_version": "v2.0",
  "shipment_id": "VTP26101800001238",
  "source_channel": "OMS_WEB",
  "source_ref": "oms.public.orders@lsn:23849120",
  "merchant_id": "MER_000845",
  "merchant_order_ref": "HM-20261018-0311",
  "partner_id": null,
  "service_type_id": "EXPRESS",
  "sender":   { "name": "Shop Mỹ Phẩm Hoa Mai", "phone": "0987654321",
                "province_id": "P01", "district_id": "P01_D05", "ward_id": "P01_D05_W03",
                "address_raw": "Số 12 ngõ 45 phố Huế, Hai Bà Trưng, Hà Nội",
                "address_match_score": 1.0 },
  "receiver": { "name": "Nguyễn Thị Lan", "phone": "0912345678",
                "province_id": "P79", "district_id": "P79_D01", "ward_id": "P79_D01_W04",
                "new_province_code": "79", "new_ward_code": "26734",
                "address_raw": "102 Nguyễn Huệ, Phường Bến Nghé, Quận 1, TP.HCM",
                "address_match_score": 0.97 },
  "pickup_facility_id": "BC_P01_0007",
  "delivery_facility_id": "BC_P79_0042",
  "parcel": { "item_category": "COSMETICS", "item_quantity": 3, "is_fragile": true,
              "weight_gram": 1200, "length_cm": 30, "width_cm": 20, "height_cm": 15,
              "volumetric_weight_gram": 1500, "charged_weight_gram": 1500 },
  "declared_value_vnd": 450000,
  "cod_amount_vnd": 450000,
  "fee_payer": "SENDER",
  "zone_type": "INTER_PROVINCE",
  "quote": { "pricing_version": "PV2026_10", "main_fee_vnd": 54000, "fuel_surcharge_vnd": 5400,
             "remote_area_fee_vnd": 0, "insurance_fee_vnd": 0, "cod_fee_vnd": 5000,
             "discount_vnd": 5400, "total_fee_vnd": 59000 },
  "fee_check": { "expected_total_fee_vnd": 59000, "delta_vnd": 0, "status": "MATCH" },
  "promised_delivery_at": "2026-10-20T23:12:05+07:00",
  "sla_leg_deadlines": { "pickup_by": "2026-10-18T13:12:05+07:00",
                         "depart_origin_hub_by": "2026-10-18T23:12:05+07:00",
                         "arrive_dest_hub_by": "2026-10-20T05:12:05+07:00" },
  "dq_flags": [],
  "dq_warnings": []
}
```

Các sự kiện vòng đời canonical khác sinh ra từ cập nhật OMS:

```json
{ "event_type": "order_updated", "shipment_id": "VTP26101800001238",
  "event_time": "2026-10-19T08:30:00+07:00", "source_channel": "OMS_WEB",
  "changed_fields": { "receiver.phone": { "old": "0912345678", "new": "0938112233" } } }
```

```json
{ "event_type": "order_cancelled", "shipment_id": "VTP26101800001303",
  "event_time": "2026-10-18T09:40:10+07:00", "source_channel": "OMS_APP",
  "cancel_reason": "MERCHANT_REQUEST" }
```

Ví dụ lệch cước:

```json
{ "event_type": "order_created", "shipment_id": "VTP26101800001253", "source_channel": "PARTNER_API",
  "quote": { "pricing_version": "PV2026_07", "total_fee_vnd": 67200 },
  "fee_check": { "expected_pricing_version": "PV2026_10", "expected_total_fee_vnd": 73300,
                 "delta_vnd": -6100, "status": "MISMATCH", "reason": "STALE_PRICING_VERSION" },
  "dq_flags": ["FEE_MISMATCH"] }
```

Bản ghi DLQ (`logistics.orders.dlq`):

```json
{
  "dlq_id": "d1f0b5a2-…", "failed_at": "2026-10-18T11:02:41+07:00",
  "source_channel": "BULK_UPLOAD", "source_ref": "MER_002210_20261018_1100.csv#row=4",
  "stage": "STANDARDIZATION", "errors": ["NON_POSITIVE_WEIGHT"],
  "raw": { "...": "bản ghi gốc" }
}
```

---

## 5. Envelope chung cho sự kiện vận hành (S4, S5, S7)

| Trường | Kiểu | Null | Ý nghĩa |
|---|---|---|---|
| `event_id` | string (UUID v4) | KHÔNG | Khóa idempotency |
| `event_type` | string | KHÔNG | snake_case |
| `event_time` | ISO8601 +07:00 | KHÔNG | Thời điểm xảy ra (dùng cho watermark) |
| `processing_time` | ISO8601 +07:00 | KHÔNG | Thời điểm gửi vào Kafka (độ trễ = processing − event) |
| `schema_version` | string | KHÔNG | `v2.0` |
| `shipment_id` | string | KHÔNG* | Mã vận đơn |
| `source_system` | string | KHÔNG | `PDA` / `SHIPPER_APP` / `FINANCE` |
| `device_id` | string | CÓ | ID máy quét / điện thoại (S4, S5) |

\* `shipment_id = null` chỉ với sự kiện gộp nhiều vận đơn: `cod_remitted` (S5) và
`merchant_settlement` (S7); danh sách vận đơn nằm trong mảng `shipments[]` / `lines[]`.

---

## 6. S4 — Quét mã tại cơ sở (`logistics.tracking.events`)

Khóa phân vùng `facility_id`. Trường chung: `facility_id`, `facility_type`, `sequence_no`,
`scanned_by` (mã nhân viên).

| `event_type` | Trường bổ sung |
|---|---|
| `arrived_at_origin_post_office` | `scan_weight_gram` (cân lại tại quầy) |
| `departed_origin_post_office` | `route_id`, `next_facility_id` |
| `arrived_at_hub` | `route_id`, `prev_facility_id` |
| `sorted_at_hub` | `sort_lane`, `next_facility_id` |
| `departed_hub` | `route_id`, `next_facility_id` |
| `arrived_at_destination_post_office` | `prev_facility_id` |
| `dispatched_for_delivery` | `shipper_id`, `attempt_no` |
| `return_initiated` | `return_reason_code` (`MAX_ATTEMPTS_REACHED` / `RECEIVER_REFUSED` / `MERCHANT_REQUEST`) — quét chuyển hoàn tại bưu cục đích, sau lần giao thất bại cuối |
| `returned_to_sender` | `return_reason_code` (quét tại bưu cục gốc khi hàng hoàn về) |
| `exception_reported` | `exception_code` (`DAMAGED` / `MISSORTED` / `LABEL_UNREADABLE` / `MISSING_ON_ARRIVAL`), `note` |

Ví dụ xuyên suốt (toàn bộ chuỗi sự kiện):

```json
{"event_id":"9a1c…01","event_type":"arrived_at_origin_post_office","event_time":"2026-10-18T11:35:02+07:00","processing_time":"2026-10-18T11:35:03+07:00","schema_version":"v2.0","shipment_id":"VTP26101800001238","source_system":"PDA","device_id":"PDA-BC_P01_0007-03","facility_id":"BC_P01_0007","facility_type":"POST_OFFICE","sequence_no":1,"scanned_by":"STF_P01_0412","scan_weight_gram":2100}
{"event_id":"9a1c…02","event_type":"departed_origin_post_office","event_time":"2026-10-18T13:05:47+07:00","processing_time":"2026-10-18T13:05:48+07:00","schema_version":"v2.0","shipment_id":"VTP26101800001238","source_system":"PDA","device_id":"PDA-BC_P01_0007-03","facility_id":"BC_P01_0007","facility_type":"POST_OFFICE","sequence_no":2,"scanned_by":"STF_P01_0412","route_id":"LH_P01_P79_0012","next_facility_id":"HUB_P01_01"}
{"event_id":"9a1c…03","event_type":"arrived_at_hub","event_time":"2026-10-18T14:02:10+07:00","processing_time":"2026-10-18T14:02:11+07:00","schema_version":"v2.0","shipment_id":"VTP26101800001238","source_system":"PDA","device_id":"PDA-HUB_P01_01-17","facility_id":"HUB_P01_01","facility_type":"HUB","sequence_no":3,"scanned_by":"STF_P01_1033","route_id":"LH_P01_P79_0012","prev_facility_id":"BC_P01_0007"}
{"event_id":"9a1c…04","event_type":"sorted_at_hub","event_time":"2026-10-18T18:20:33+07:00","processing_time":"2026-10-18T18:20:33+07:00","schema_version":"v2.0","shipment_id":"VTP26101800001238","source_system":"PDA","device_id":"SORTER-HUB_P01_01-A","facility_id":"HUB_P01_01","facility_type":"HUB","sequence_no":4,"scanned_by":"SORTER","sort_lane":"L12-HCM","next_facility_id":"HUB_P79_01"}
{"event_id":"9a1c…05","event_type":"departed_hub","event_time":"2026-10-18T19:45:00+07:00","processing_time":"2026-10-18T19:45:02+07:00","schema_version":"v2.0","shipment_id":"VTP26101800001238","source_system":"PDA","device_id":"PDA-HUB_P01_01-21","facility_id":"HUB_P01_01","facility_type":"HUB","sequence_no":5,"scanned_by":"STF_P01_1050","route_id":"LH_P01_P79_0012","next_facility_id":"HUB_P79_01"}
{"event_id":"9a1c…06","event_type":"arrived_at_hub","event_time":"2026-10-19T15:30:12+07:00","processing_time":"2026-10-19T15:30:13+07:00","schema_version":"v2.0","shipment_id":"VTP26101800001238","source_system":"PDA","device_id":"PDA-HUB_P79_01-08","facility_id":"HUB_P79_01","facility_type":"HUB","sequence_no":6,"scanned_by":"STF_P79_2210","route_id":"LH_P01_P79_0012","prev_facility_id":"HUB_P01_01"}
{"event_id":"9a1c…07","event_type":"sorted_at_hub","event_time":"2026-10-19T19:10:40+07:00","processing_time":"2026-10-19T19:10:40+07:00","schema_version":"v2.0","shipment_id":"VTP26101800001238","source_system":"PDA","device_id":"SORTER-HUB_P79_01-B","facility_id":"HUB_P79_01","facility_type":"HUB","sequence_no":7,"scanned_by":"SORTER","sort_lane":"L03-Q1","next_facility_id":"BC_P79_0042"}
{"event_id":"9a1c…08","event_type":"departed_hub","event_time":"2026-10-19T21:05:18+07:00","processing_time":"2026-10-19T21:05:19+07:00","schema_version":"v2.0","shipment_id":"VTP26101800001238","source_system":"PDA","device_id":"PDA-HUB_P79_01-12","facility_id":"HUB_P79_01","facility_type":"HUB","sequence_no":8,"scanned_by":"STF_P79_2231","route_id":null,"next_facility_id":"BC_P79_0042"}
{"event_id":"9a1c…09","event_type":"arrived_at_destination_post_office","event_time":"2026-10-19T22:40:05+07:00","processing_time":"2026-10-19T22:40:06+07:00","schema_version":"v2.0","shipment_id":"VTP26101800001238","source_system":"PDA","device_id":"PDA-BC_P79_0042-02","facility_id":"BC_P79_0042","facility_type":"POST_OFFICE","sequence_no":9,"scanned_by":"STF_P79_0877","prev_facility_id":"HUB_P79_01"}
{"event_id":"9a1c…10","event_type":"dispatched_for_delivery","event_time":"2026-10-20T07:55:30+07:00","processing_time":"2026-10-20T07:55:31+07:00","schema_version":"v2.0","shipment_id":"VTP26101800001238","source_system":"PDA","device_id":"PDA-BC_P79_0042-02","facility_id":"BC_P79_0042","facility_type":"POST_OFFICE","sequence_no":10,"scanned_by":"STF_P79_0877","shipper_id":"SHP_P79_004518","attempt_no":1}
{"event_id":"9a1c…11","event_type":"dispatched_for_delivery","event_time":"2026-10-21T08:02:15+07:00","processing_time":"2026-10-21T08:02:16+07:00","schema_version":"v2.0","shipment_id":"VTP26101800001238","source_system":"PDA","device_id":"PDA-BC_P79_0042-02","facility_id":"BC_P79_0042","facility_type":"POST_OFFICE","sequence_no":11,"scanned_by":"STF_P79_0877","shipper_id":"SHP_P79_004518","attempt_no":2}
```

Ví dụ sự cố (một vận đơn khác):

```json
{"event_type":"exception_reported","event_time":"2026-10-18T16:10:00+07:00","shipment_id":"VTP26101800001261","source_system":"PDA","facility_id":"HUB_P48_01","facility_type":"HUB","sequence_no":4,"scanned_by":"STF_P48_0301","exception_code":"DAMAGED","note":"Thùng móp góc, hàng bên trong còn nguyên"}
```

---

## 7. S5 — App shipper (`logistics.shipper.events`)

Khóa phân vùng `shipper_id`. Trường chung: `shipper_id`, `facility_id`, `gps_lat`, `gps_lon`.

| `event_type` | Trường bổ sung |
|---|---|
| `pickup_task_assigned` | `task_id`, `due_by` |
| `picked_up` | `task_id`, `actual_weight_gram`, `actual_length_cm/width_cm/height_cm`, `parcel_count`, `photo_ref` |
| `pickup_failed` | `task_id`, `failure_reason_code` (`SENDER_ABSENT` / `GOODS_NOT_READY` / `PROHIBITED_ITEM`), `reschedule_at` |
| `delivered` | `attempt_no`, `recipient_relation`, `pod_type` (`OTP` / `SIGNATURE` / `PHOTO`), `pod_ref`, `cod_collected_vnd`, `fee_collected_vnd`, `payment_method` (`CASH` / `QR` / `NONE`) |
| `failed_delivery` | `attempt_no`, `failure_reason_code`, `failure_note`, `reschedule_at`, `call_attempts` |
| `cod_remitted` | `remit_id`, `shift_date`, `shipments[]` (`shipment_id`, `cod_collected_vnd`, `fee_collected_vnd`), `expected_total_vnd`, `remitted_total_vnd`, `received_by` |

Ví dụ xuyên suốt:

```json
{"event_id":"5d2e…01","event_type":"pickup_task_assigned","event_time":"2026-10-18T09:14:30+07:00","processing_time":"2026-10-18T09:14:31+07:00","schema_version":"v2.0","shipment_id":"VTP26101800001238","source_system":"SHIPPER_APP","device_id":"APP-SHP_P01_000231","shipper_id":"SHP_P01_000231","facility_id":"BC_P01_0007","gps_lat":null,"gps_lon":null,"task_id":"PU-20261018-0007-0192","due_by":"2026-10-18T13:12:05+07:00"}
{"event_id":"5d2e…02","event_type":"picked_up","event_time":"2026-10-18T10:41:12+07:00","processing_time":"2026-10-18T10:41:15+07:00","schema_version":"v2.0","shipment_id":"VTP26101800001238","source_system":"SHIPPER_APP","device_id":"APP-SHP_P01_000231","shipper_id":"SHP_P01_000231","facility_id":"BC_P01_0007","gps_lat":21.01452,"gps_lon":105.85031,"task_id":"PU-20261018-0007-0192","actual_weight_gram":2100,"actual_length_cm":30,"actual_width_cm":20,"actual_height_cm":15,"parcel_count":1,"photo_ref":"s3://pod/pickup/VTP26101800001238.jpg"}
{"event_id":"5d2e…03","event_type":"failed_delivery","event_time":"2026-10-20T10:05:10+07:00","processing_time":"2026-10-20T14:12:30+07:00","schema_version":"v2.0","shipment_id":"VTP26101800001238","source_system":"SHIPPER_APP","device_id":"APP-SHP_P79_004518","shipper_id":"SHP_P79_004518","facility_id":"BC_P79_0042","gps_lat":10.77391,"gps_lon":106.70412,"attempt_no":1,"failure_reason_code":"PHONE_NOT_ANSWERED","failure_note":"Gọi 3 lần không nghe máy","call_attempts":3,"reschedule_at":"2026-10-21T08:00:00+07:00"}
{"event_id":"5d2e…04","event_type":"delivered","event_time":"2026-10-21T09:20:44+07:00","processing_time":"2026-10-21T09:20:46+07:00","schema_version":"v2.0","shipment_id":"VTP26101800001238","source_system":"SHIPPER_APP","device_id":"APP-SHP_P79_004518","shipper_id":"SHP_P79_004518","facility_id":"BC_P79_0042","gps_lat":10.77402,"gps_lon":106.70398,"attempt_no":2,"recipient_relation":"SELF","pod_type":"OTP","pod_ref":"otp:verified","cod_collected_vnd":450000,"fee_collected_vnd":0,"payment_method":"CASH"}
```

Sự kiện `failed_delivery` ở trên là **sự kiện đến trễ**: điện thoại mất mạng, nên
`processing_time − event_time` ≈ 4 giờ 07 phút.

Nộp tiền theo ca (gộp nhiều vận đơn, `shipment_id = null`). Cuối ca shipper nộp toàn bộ tiền
đã thu (COD + cước người nhận trả) về bưu cục; `expected_total_vnd` do app tính từ các lần
`delivered` trong ca:

```json
{
  "event_id": "5d2e…05", "event_type": "cod_remitted",
  "event_time": "2026-10-21T18:05:00+07:00", "processing_time": "2026-10-21T18:05:02+07:00",
  "schema_version": "v2.0", "shipment_id": null, "source_system": "SHIPPER_APP",
  "device_id": "APP-SHP_P79_004518", "shipper_id": "SHP_P79_004518", "facility_id": "BC_P79_0042",
  "gps_lat": null, "gps_lon": null,
  "remit_id": "RM-20261021-BC_P79_0042-0031", "shift_date": "2026-10-21",
  "shipments": [
    { "shipment_id": "VTP26101800001238", "cod_collected_vnd": 450000, "fee_collected_vnd": 0 },
    { "shipment_id": "VTP26101900004410", "cod_collected_vnd": 1250000, "fee_collected_vnd": 32000 },
    { "shipment_id": "VTP26102000000871", "cod_collected_vnd": 0, "fee_collected_vnd": 41000 }
  ],
  "expected_total_vnd": 1773000,
  "remitted_total_vnd": 1773000,
  "received_by": "STF_P79_0877"
}
```

Ví dụ thất thoát (lỗi có gắn nhãn `COD_SHORTFALL`): `expected_total_vnd = 2.180.000`,
`remitted_total_vnd = 1.930.000`, thiếu 250.000.

---

## 8. S7 — Tài chính (`logistics.financial.events`)

Khóa phân vùng `merchant_id`. Trường chung: `transaction_id`, `merchant_id`, `facility_id`,
`branch_id`, `service_type_id` (trừ `merchant_settlement`: chỉ có `transaction_id`, `merchant_id`).

| `event_type` | Kích hoạt bởi | Trường bổ sung |
|---|---|---|
| `fee_confirmed` | Lấy hàng, cân nặng trong ngưỡng cho phép | `pricing_version`, chi tiết cước, `total_fee_vnd` |
| `fee_adjusted` | Lấy hàng, cân nặng chênh lệch | `old_total_fee_vnd`, `new_total_fee_vnd`, `adjustment_vnd`, chi tiết cước mới, `reason_code` (`REWEIGH` / `ADDRESS_CHANGE` / `MANUAL`) |
| `return_fee_charged` | `return_initiated` | `return_fee_vnd`, `base_main_fee_vnd`, `return_fee_pct` |
| `merchant_settlement` | Hết kỳ đối soát | `settlement_id`, `period`, `lines[]` (`shipment_id`, `cod_vnd`, `fee_deducted_vnd`, `net_vnd`), `total_cod_vnd`, `total_fee_deducted_vnd`, `total_net_vnd`, `bank_account_no` |

Ví dụ xuyên suốt:

```json
{
  "event_id": "7c3b…01", "event_type": "fee_adjusted",
  "event_time": "2026-10-18T10:41:40+07:00", "processing_time": "2026-10-18T10:41:41+07:00",
  "schema_version": "v2.0", "shipment_id": "VTP26101800001238", "source_system": "FINANCE",
  "transaction_id": "TX-20261018-000452117", "merchant_id": "MER_000845",
  "facility_id": "BC_P01_0007", "branch_id": "CN_P01_002", "service_type_id": "EXPRESS",
  "pricing_version": "PV2026_10", "reason_code": "REWEIGH",
  "old_charged_weight_gram": 1500, "new_charged_weight_gram": 2100,
  "main_fee_vnd": 70000, "fuel_surcharge_vnd": 7000, "remote_area_fee_vnd": 0,
  "insurance_fee_vnd": 0, "cod_fee_vnd": 5000, "discount_vnd": 7000,
  "old_total_fee_vnd": 59000, "new_total_fee_vnd": 75000, "adjustment_vnd": 16000
}
```

`70.000 = 38.000 + ⌈(2.100 − 500) / 500⌉ × 8.000`; xăng dầu 10%; chiết khấu 10% cước chính.

Phí hoàn:

```json
{ "event_type": "return_fee_charged", "event_time": "2026-10-22T15:00:00+07:00",
  "shipment_id": "VTP26101800001253", "source_system": "FINANCE",
  "transaction_id": "TX-20261022-000003310", "merchant_id": "MER_000845",
  "base_main_fee_vnd": 55000, "return_fee_pct": 0.5, "return_fee_vnd": 27500 }
```

Đối soát với shop (`merchant_settlement`). Đối soát hai chiều: shop nhận COD, đồng thời trả
cước và phí hoàn. **Mỗi sự kiện ứng với một merchant trong một kỳ** (`merchants.payout_cycle`:
DAILY / WEEKLY): tài chính gộp mọi vận đơn của shop **kết thúc** trong kỳ (giao thành công
hoặc hoàn về) thành các dòng `lines[]`. Shop không có đơn nào kết thúc trong kỳ thì không
phát sự kiện.

- `cod_vnd` = COD thực thu (`delivered.cod_collected_vnd`); đơn hoàn = 0.
- `fee_deducted_vnd` = cước chốt (`fee_confirmed` / `fee_adjusted`) nếu `fee_payer = SENDER`,
  cộng `return_fee_vnd` nếu đơn hoàn. Đơn `fee_payer = RECEIVER` giao thành công thì cước đã
  thu tại cửa → 0.
- `net_vnd = cod_vnd − fee_deducted_vnd` (có thể âm: đơn không COD vẫn phải trả cước).
- `total_*` = tổng các dòng; `total_net_vnd` là số tiền chuyển cho shop (âm → shop nợ, cộng dồn kỳ sau).

```json
{
  "event_id": "7c3b…02", "event_type": "merchant_settlement",
  "event_time": "2026-10-22T02:00:00+07:00", "processing_time": "2026-10-22T02:00:04+07:00",
  "schema_version": "v2.0", "shipment_id": null, "source_system": "FINANCE",
  "transaction_id": "TX-20261022-000001877", "merchant_id": "MER_000845",
  "settlement_id": "ST-20261022-MER_000845", "period": "2026-10-21",
  "lines": [
    { "shipment_id": "VTP26101800001238", "cod_vnd": 450000, "fee_deducted_vnd": 75000, "net_vnd": 375000 },
    { "shipment_id": "VTP26101900002291", "cod_vnd": 0, "fee_deducted_vnd": 41000, "net_vnd": -41000 }
  ],
  "total_cod_vnd": 450000, "total_fee_deducted_vnd": 116000, "total_net_vnd": 334000,
  "bank_account_no": "0451000123456"
}
```

---

## 9. S9 — Dữ liệu tham chiếu tĩnh

Các dim hiện có (`dim_province`, `dim_district`, `dim_ward`, `dim_region`, `dim_branch`,
`dim_facility`, `dim_service_type`, `dim_route`, `dim_partner`, `dim_shipper`, `dim_date`)
giữ schema trong [schema_design.md](schema_design.md). Các bảng tham chiếu mới:

`ref_status_transition`: state machine được biểu diễn dưới dạng dữ liệu.

| from_state | event_type | to_state | phase |
|---|---|---|---|
| — | order_created | CREATED | ORDER |
| CREATED | order_cancelled | CANCELLED | ORDER |
| CREATED | pickup_task_assigned | PICKUP_ASSIGNED | FIRST_MILE |
| PICKUP_ASSIGNED | pickup_failed | PICKUP_ASSIGNED | FIRST_MILE |
| PICKUP_ASSIGNED | picked_up | PICKED_UP | FIRST_MILE |
| PICKED_UP | arrived_at_origin_post_office | AT_ORIGIN_PO | FIRST_MILE |
| AT_ORIGIN_PO | departed_origin_post_office | IN_TRANSIT | MIDDLE_MILE |
| IN_TRANSIT | arrived_at_hub | AT_HUB | MIDDLE_MILE |
| AT_HUB | sorted_at_hub | SORTED | MIDDLE_MILE |
| SORTED | departed_hub | IN_TRANSIT | MIDDLE_MILE |
| IN_TRANSIT | arrived_at_destination_post_office | AT_DEST_PO | LAST_MILE |
| AT_DEST_PO | dispatched_for_delivery | OUT_FOR_DELIVERY | LAST_MILE |
| OUT_FOR_DELIVERY | delivered | DELIVERED | LAST_MILE |
| OUT_FOR_DELIVERY | failed_delivery | DELIVERY_FAILED | LAST_MILE |
| DELIVERY_FAILED | dispatched_for_delivery | OUT_FOR_DELIVERY | LAST_MILE |
| DELIVERY_FAILED | return_initiated | RETURNING | RETURN |
| RETURNING | returned_to_sender | RETURNED | RETURN |
| * | exception_reported | (không đổi) | ANY |

Mọi cặp (trạng thái, sự kiện) không có trong bảng được đưa vào `invalid_transitions`.

`ref_failure_reason`

| reason_code | reason_name_vi | category | is_customer_fault |
|---|---|---|---|
| RECEIVER_ABSENT | Người nhận vắng nhà | RECEIVER | true |
| PHONE_NOT_ANSWERED | Không liên lạc được | RECEIVER | true |
| WRONG_ADDRESS | Sai địa chỉ | SENDER | true |
| RECEIVER_REFUSED | Từ chối nhận | RECEIVER | true |
| DAMAGED_PACKAGE | Hàng hư hỏng | CARRIER | false |
| OUTSIDE_DELIVERY_HOURS | Ngoài giờ giao | CARRIER | false |

`ref_admin_unit_mapping`: 3 cấp cũ → 2 cấp sau tháng 7/2025 (mã mang tính minh họa)

| old_province_id | old_district_id | old_ward_id | old_ward_name | new_province_code | new_province_name | new_ward_code | new_ward_name |
|---|---|---|---|---|---|---|---|
| P79 | P79_D01 | P79_D01_W04 | Phường Bến Nghé | 79 | Thành phố Hồ Chí Minh | 26734 | Phường Sài Gòn |
| P74 | P74_D02 | P74_D02_W01 | Phường Phú Cường | 79 | Thành phố Hồ Chí Minh | 25747 | Phường Thủ Dầu Một |

`ref_address_alias`: từ điển phục vụ chuẩn hóa

| alias | normalized | level |
|---|---|---|
| TP HCM, TPHCM, HCM, Sài Gòn | Thành phố Hồ Chí Minh | PROVINCE |
| Q10, Q.10, Quận 10 | Quận 10 | DISTRICT |
| P.10, F10, Phường 10 | Phường 10 | WARD |

---


## 10. Nhãn ground truth (`sim_labels/`, chỉ dùng để đánh giá)

Mọi nghiệp vụ phải có chỉ số đo được (precision/recall cảnh báo, tỷ lệ phát hiện lỗi DQ, …),
nên cần **đáp án đúng** để so. Dữ liệu thật không có đáp án; dữ liệu giả lập thì có, vì chính
bộ giả lập cố ý tiêm lỗi nên biết chính xác bản ghi nào sai và sai kiểu gì. Bảng này là nơi bộ
giả lập ghi đáp án đó: một dòng cho mỗi lỗi nó tiêm (và mỗi địa chỉ nó cố ý làm nhiễu).

- Pipeline **không bao giờ đọc** bảng này (đọc thì như nhìn đáp án khi làm bài).
- Chỉ **job đánh giá** đọc nó: join nhãn với đầu ra của pipeline (DLQ, `invalid_transitions`,
  bảng cảnh báo, …) qua `record_ref` / `shipment_id`, rồi tính chỉ số theo từng `fault_type`.

Ví dụ: tiêm 100 dòng `INVALID_PHONE`; DQ từ chối 98 dòng, trong đó 95 dòng có nhãn và 3 dòng
là đơn sạch bị bắt nhầm → recall = 95/100 = 95%, precision = 95/98 ≈ 97%.

Ý nghĩa các cột chính: `fault_type` để nhóm khi tính chỉ số; `record_ref` là khóa join với đầu
ra của pipeline; `expected_detection` cho biết thành phần nào của pipeline phải bắt được lỗi;
`expected_value` là đáp án khi cần so giá trị. `ADDRESS_NOISE` không phải lỗi bị từ chối mà là
bài kiểm tra cho bước chuẩn hóa địa chỉ (đo tỷ lệ ra đúng `expected_value`).

Lưu dạng Parquet trên MinIO / S3: `sim_labels/date=YYYY-MM-DD/labels-<run_id>-<seq>.parquet`.

| Cột | Kiểu | Null | Ý nghĩa |
|---|---|---|---|
| `label_id` | string | KHÔNG | `L-<run_id>-<seq>` |
| `run_id` | string | KHÔNG | Lần chạy giả lập |
| `shipment_id` | string | CÓ | Null khi bản ghi bị từ chối trước khi cấp mã (S2 DLQ, dòng CSV lỗi) |
| `source` | string | KHÔNG | `S1` / `S2` / `S3` / `S4` / `S5` / `S7` |
| `fault_type` | string | KHÔNG | Xem danh mục dưới |
| `injected_at` | timestamp +07:00 | KHÔNG | Thời điểm nghiệp vụ của bản ghi bị tiêm lỗi |
| `record_ref` | string | CÓ | Định vị bản ghi: `event_id`, `request_id`, `file_path#row=N`, `remit_id` |
| `detail` | string | CÓ | Mô tả ngắn cho người đọc |
| `expected_value` | string | CÓ | Giá trị đúng (vd `ward_id` đúng của địa chỉ nhiễu, tổng cước đúng) |
| `expected_detection` | string | KHÔNG | Cơ chế phía pipeline phải bắt được lỗi này |

Danh mục `fault_type`:

| fault_type | Nguồn | Cách tiêm | expected_detection |
|---|---|---|---|
| `INVALID_PHONE` | S2, S3 | SĐT sai độ dài / sai đầu số | DQ từ chối (gateway 400 hoặc dòng import REJECTED) |
| `NON_POSITIVE_WEIGHT` | S3 | Khối lượng ≤ 0 | DQ từ chối |
| `NEGATIVE_COD` | S3 | COD âm | DQ từ chối |
| `MISSING_FIELD` | S2, S3 | Bỏ trống trường bắt buộc (tên / SĐT / địa chỉ người nhận) | DQ từ chối |
| `CROSS_CHANNEL_DUPLICATE` | S2, S3 | Gửi lại đơn đã tạo ở kênh khác, cùng `(merchant_id, merchant_order_ref)` | Khử trùng theo khóa nghiệp vụ |
| `STALE_PRICING_VERSION` | S1, S2 | Báo giá theo phiên bản bảng giá đã hết hiệu lực | `FEE_MISMATCH` |
| `MISSING_REMOTE_FEE` | S1, S2 | Bỏ phụ phí vùng xa cho đơn đi vùng xa | `FEE_MISMATCH` |
| `WRONG_INSURANCE` | S1, S2 | Tính sai phí bảo hiểm | `FEE_MISMATCH` |
| `ADDRESS_NOISE` | S2, S3 | Viết tắt, bỏ dấu, dùng tên cũ trước 2025, thiếu cấp | Chuẩn hóa ra đúng `expected_value` (đo độ chính xác, không phải lỗi) |
| `LATE_EVENT` | S4, S5 | Giữ sự kiện lại trước khi gửi Kafka | Watermark / sắp xếp lại; vượt watermark → ghi `late_events` |
| `DUPLICATE_EVENT` | S4, S5 | Gửi lại cùng sự kiện, cùng `event_id` | Khử trùng theo `event_id` |
| `INVALID_TRANSITION` | S4, S5 | Phát sự kiện không hợp lệ với trạng thái hiện tại (vd `delivered` khi chưa `dispatched_for_delivery`) | `invalid_transitions` |
| `ORPHAN_EVENT` | S4 | Quét mã một `shipment_id` không tồn tại | `ORPHAN_EVENT` sau thời gian chờ |
| `STUCK` | S4 | Dừng phát mọi sự kiện sau một lần quét | Cảnh báo `STUCK` → `LOST` |
| `MISROUTE` | S4 | Chuyển hàng tới hub khác hub mà tuyến yêu cầu | `ABNORMAL_ROUTE` |
| `COD_SHORTFALL` | S5 | `remitted_total_vnd < expected_total_vnd` | Đối soát COD |

Ví dụ:

| label_id | shipment_id | source | fault_type | injected_at | detail | expected_detection |
|---|---|---|---|---|---|---|
| L-000101 | — | S3 | INVALID_PHONE | 2026-10-18T11:00:12+07:00 | dòng 3, `09123` | DQ từ chối |
| L-000102 | — | S3 | NON_POSITIVE_WEIGHT | 2026-10-18T11:00:12+07:00 | dòng 4, `-300` | DQ từ chối |
| L-000103 | VTP26101700009915 | S3 | CROSS_CHANNEL_DUPLICATE | 2026-10-18T11:00:12+07:00 | dòng 6 = đơn OMS_APP `LC-1017-088` | khử trùng từ chối |
| L-000104 | VTP26101800001253 | S2 | STALE_PRICING_VERSION | 2026-10-18T10:15:40+07:00 | báo giá theo PV2026_07 | FEE_MISMATCH |
| L-000105 | VTP26101800001238 | S5 | LATE_EVENT | 2026-10-20T10:05:10+07:00 | failed_delivery trễ 4 giờ 07 phút | watermark / reorder |
| L-000106 | VTP26101900007710 | S4 | STUCK | 2026-10-19T12:00:00+07:00 | không có lần quét nào sau arrived_at_hub | cảnh báo STUCK → LOST |
| L-000107 | — | S5 | COD_SHORTFALL | 2026-10-21T18:30:00+07:00 | phiếu nộp RM-…-0044 thiếu 250.000 | đối soát |
| L-000108 | VTP26101800001311 | S4 | DUPLICATE_EVENT | 2026-10-18T14:20:00+07:00 | cùng một lần quét gửi lại với cùng event_id | khử trùng |
| L-000109 | VTP26101800001329 | S4 | MISROUTE | 2026-10-18T20:10:00+07:00 | đến HUB_P48_01, tuyến yêu cầu HUB_P79_01 | ABNORMAL_ROUTE |

---

## 11. Các nguồn làm sau (hình dạng nháp)

Bản ghi GPS S6 (`logistics.gps.pings`, khóa phân vùng `device_id`):

```json
{ "event_id": "…", "event_time": "2026-10-21T09:18:30+07:00", "device_id": "APP-SHP_P79_004518",
  "entity_type": "SHIPPER", "entity_id": "SHP_P79_004518", "lat": 10.77385, "lon": 106.70401,
  "speed_kmh": 18.5, "heading": 92, "accuracy_m": 6, "battery_pct": 54 }
```

Dòng sao kê ngân hàng S8 (`landing/bank/2026-10-22/statement.csv`):

```csv
txn_date,value_date,bank_txn_ref,account_no,direction,amount_vnd,counterparty,description
2026-10-21,2026-10-21,FT26294A11B2,0011009988776,CREDIT,1773000,BC_P79_0042,NOP COD RM-20261021-BC_P79_0042-0031
2026-10-22,2026-10-22,FT26295C33D4,0011009988776,DEBIT,334000,0451000123456,CHI TRA COD ST-20261022-MER_000845
```

---

