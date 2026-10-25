-- S1 OMS — DDL theo docs/data_samples.md §1.1.
-- Chỉ chạy khi volume Postgres còn trống (docker-entrypoint-initdb.d).

CREATE TABLE merchants (
    merchant_id          VARCHAR(16) PRIMARY KEY,      -- MER_000845
    merchant_name        TEXT NOT NULL,
    merchant_type        VARCHAR(16) NOT NULL,         -- INDIVIDUAL / SME / ENTERPRISE
    phone                VARCHAR(16),
    email                TEXT,
    pickup_address       TEXT NOT NULL,                -- văn bản tự do, như khách nhập
    pickup_province_id   VARCHAR(8),
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
    sender_ward_id         VARCHAR(24),
    pickup_facility_id     VARCHAR(16) NOT NULL,
    -- người nhận
    receiver_name          TEXT NOT NULL,
    receiver_phone         VARCHAR(16) NOT NULL,
    receiver_address       TEXT NOT NULL,
    receiver_province_id   VARCHAR(8),
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

-- Số thứ tự trong shipment_id = VTP{yymmdd}{nextval:08d}, dùng chung cho OMS / gateway / import.
CREATE SEQUENCE shipment_seq;

-- CDC: bản ghi UPDATE mang đủ "before" (§1.3).
ALTER TABLE merchants     REPLICA IDENTITY FULL;
ALTER TABLE pricing_rules REPLICA IDENTITY FULL;
ALTER TABLE sla_config    REPLICA IDENTITY FULL;
ALTER TABLE orders        REPLICA IDENTITY FULL;

CREATE PUBLICATION oms_publication FOR TABLE merchants, pricing_rules, sla_config, orders;
