#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import random
from datetime import datetime, time, timedelta, timezone

from simulation.reference.catalog import SEED, _TEN, build_catalog

TZ = timezone(timedelta(hours=7))
DEFAULT_DSN = "postgresql://oms:oms@localhost:5432/oms"
N_MERCHANTS = 1_000

SERVICES = ["SAMEDAY", "EXPRESS", "NEXTDAY", "STANDARD", "ECONOMY"]   # dịch vụ gốc có bảng giá
ZONES = ["INNER_CITY", "SAME_PROVINCE", "INTER_PROVINCE", "REMOTE"]

# Bảng giá PV2026_10: (first_weight_fee, step_fee) theo dịch vụ × vùng, nấc đầu 500 g, mỗi bước 500 g
_FEES_PV2026_10 = {
    "SAMEDAY":  [(30000, 6000), (38000, 7000), (55000, 10000), (65000, 12000)],
    "EXPRESS":  [(22000, 5000), (28000, 6000), (38000, 8000), (45000, 9000)],
    "NEXTDAY":  [(20000, 4500), (25000, 5500), (34000, 7000), (40000, 8000)],
    "STANDARD": [(16000, 3500), (19000, 4000), (25000, 5000), (30000, 6000)],
    "ECONOMY":  [(13000, 3000), (15000, 3500), (20000, 4000), (24000, 5000)],
}
# (pricing_version, hệ số giá so với PV2026_10, fuel_surcharge_pct, effective_from, effective_to)
_VERSIONS = [
    ("PV2026_07", 0.95, 0.08, datetime(2026, 7, 1, tzinfo=TZ), datetime(2026, 10, 1, tzinfo=TZ)),
    ("PV2026_10", 1.00, 0.10, datetime(2026, 10, 1, tzinfo=TZ), None),
]

# sla_config: dịch vụ → vùng → (pickup, first_mile, linehaul, last_mile) giờ; total = tổng 4 chặng
_SLA_LEGS = {
    "SAMEDAY":  {"INNER_CITY": (2, 2, 1, 3), "SAME_PROVINCE": (2, 3, 3, 4),
                 "INTER_PROVINCE": (3, 5, 8, 8), "REMOTE": (3, 5, 12, 16)},
    "EXPRESS":  {"INNER_CITY": (3, 4, 4, 13), "SAME_PROVINCE": (3, 6, 10, 17),
                 "INTER_PROVINCE": (4, 10, 30, 18), "REMOTE": (4, 10, 36, 36)},
    "NEXTDAY":  {"INNER_CITY": (4, 6, 6, 14), "SAME_PROVINCE": (4, 8, 12, 16),
                 "INTER_PROVINCE": (6, 12, 30, 24), "REMOTE": (6, 12, 40, 38)},
    "STANDARD": {"INNER_CITY": (6, 8, 10, 24), "SAME_PROVINCE": (8, 10, 16, 26),
                 "INTER_PROVINCE": (8, 14, 60, 28), "REMOTE": (8, 14, 70, 48)},
    "ECONOMY":  {"INNER_CITY": (8, 12, 16, 36), "SAME_PROVINCE": (8, 16, 30, 42),
                 "INTER_PROVINCE": (12, 18, 80, 40), "REMOTE": (12, 18, 100, 60)},
}
_CUTOFF = {"SAMEDAY": time(12), "EXPRESS": time(17), "NEXTDAY": time(17),
           "STANDARD": time(16), "ECONOMY": time(15)}

_STREETS = ["Lê Lợi", "Trần Hưng Đạo", "Nguyễn Trãi", "Hai Bà Trưng", "Lý Thường Kiệt", "Quang Trung",
            "Hùng Vương", "Nguyễn Huệ", "Phan Chu Trinh", "Lê Duẩn", "Trần Phú", "Điện Biên Phủ",
            "Nguyễn Văn Linh", "Võ Văn Kiệt", "Lê Văn Việt", "Cách Mạng Tháng Tám"]
_SHOP_KINDS = ["Mỹ Phẩm", "Thời Trang", "Gia Dụng", "Điện Máy", "Sách", "Đồ Chơi", "Thực Phẩm", "Phụ Kiện"]
_PHONE_PREFIX = ["090", "091", "093", "097", "098", "032", "035", "070", "077", "086"]

# 3 shop của ví dụ trong docs/data_samples.md §1.2, để chạy lại được các request mẫu
_DOC_MERCHANTS = [
    {"merchant_id": "MER_000845", "merchant_name": "Shop Mỹ Phẩm Hoa Mai", "merchant_type": "SME",
     "phone": "0987654321", "pickup_address": "Số 12 ngõ 45 phố Huế, Phường Hai Bà Trưng, Hà Nội",
     "pickup_province_id": "P01", "pickup_ward_id": "P01_W00256", "contract_type": "VOLUME",
     "discount_pct": 0.10, "payout_cycle": "DAILY"},
    {"merchant_id": "MER_001203", "merchant_name": "Gia Dụng Minh Tâm (Shopee)", "merchant_type": "SME",
     "phone": "0909111222", "pickup_address": "88 Lê Văn Việt, Phường Tăng Nhơn Phú, TP.HCM",
     "pickup_province_id": "P79", "pickup_ward_id": "P79_W26842", "contract_type": "PAY_PER_USE",
     "discount_pct": 0.0, "payout_cycle": "DAILY"},
    {"merchant_id": "MER_002210", "merchant_name": "Thời Trang Linh Chi", "merchant_type": "INDIVIDUAL",
     "phone": "0912000210", "pickup_address": "25 Trần Phú, Phường Hải Châu, Đà Nẵng",
     "pickup_province_id": "P48", "pickup_ward_id": "P48_W20242", "contract_type": "PAY_PER_USE",
     "discount_pct": 0.0, "payout_cycle": "WEEKLY"},
]


def _floor500(v: float) -> int:
    return int(v // 500 * 500)


def build_pricing_rules() -> list[dict]:
    rules = []
    for version, factor, fuel, eff_from, eff_to in _VERSIONS:
        for svc in SERVICES:
            for zone, (first_fee, step_fee) in zip(ZONES, _FEES_PV2026_10[svc]):
                rules.append({
                    "pricing_version": version, "service_type_id": svc, "zone_type": zone,
                    "first_weight_gram": 500, "first_weight_fee": _floor500(first_fee * factor),
                    "step_gram": 500, "step_fee": _floor500(step_fee * factor),
                    "volumetric_divisor": 6000, "fuel_surcharge_pct": fuel,
                    "remote_area_fee": 15000, "insurance_pct": 0.005, "insurance_threshold": 1_000_000,
                    "cod_fee_pct": 0.01, "cod_fee_min": 5000, "return_fee_pct": 0.5,
                    "effective_from": eff_from, "effective_to": eff_to,
                })
    return rules


def build_sla_config() -> list[dict]:
    return [{"service_type_id": svc, "zone_type": zone, "total_hours": sum(legs),
             "pickup_hours": legs[0], "first_mile_hours": legs[1], "linehaul_hours": legs[2],
             "last_mile_hours": legs[3], "cutoff_time": _CUTOFF[svc]}
            for svc, zones in _SLA_LEGS.items() for zone, legs in zones.items()]


def phone(rnd: random.Random) -> str:
    return rnd.choice(_PHONE_PREFIX) + f"{rnd.randint(0, 9_999_999):07d}"


def street_address(rnd: random.Random) -> str:
    if rnd.random() < 0.3:
        return f"Số {rnd.randint(1, 120)} ngõ {rnd.randint(1, 300)} {rnd.choice(_STREETS)}"
    return f"{rnd.randint(1, 500)} {rnd.choice(_STREETS)}"


def full_address(rnd: random.Random, ward: dict, province: dict) -> str:
    """Địa chỉ theo địa giới mới: '<số nhà, đường>, <xã/phường>, <tỉnh>'."""
    return f"{street_address(rnd)}, {ward['ward_name']}, {province['province_name_short']}"


def build_merchants(catalog: dict, seed: int = SEED) -> list[dict]:
    """~1.000 shop, phân bố theo số bưu cục của tỉnh; bưu cục lấy hàng ưu tiên cùng xã."""
    rnd = random.Random(seed)
    provinces = {p["province_id"]: p for p in catalog["dim_province"]}
    wards_by_prov: dict[str, list[dict]] = {}
    for w in catalog["dim_ward"]:
        wards_by_prov.setdefault(w["province_id"], []).append(w)
    po_by_prov: dict[str, list[dict]] = {}
    for f in catalog["dim_facility"]:
        if f["facility_type"] == "POST_OFFICE":
            po_by_prov.setdefault(f["province_id"], []).append(f)
    provs = list(po_by_prov)
    weights = [len(po_by_prov[p]) for p in provs]

    out = []
    for i in range(1, N_MERCHANTS + 1):
        prov = rnd.choices(provs, weights=weights, k=1)[0]
        ward = rnd.choice(wards_by_prov[prov])
        same_ward = [f for f in po_by_prov[prov] if f["ward_id"] == ward["ward_id"]]
        facility = rnd.choice(same_ward or po_by_prov[prov])
        mtype = rnd.choices(["INDIVIDUAL", "SME", "ENTERPRISE"], weights=[50, 40, 10], k=1)[0]
        contract = {"INDIVIDUAL": "PAY_PER_USE", "SME": rnd.choice(["PAY_PER_USE", "VOLUME"]),
                    "ENTERPRISE": rnd.choice(["VOLUME", "FIXED"])}[mtype]
        discount = 0.0 if contract == "PAY_PER_USE" else rnd.choice([0.05, 0.08, 0.10, 0.15])
        created = datetime(2024, 1, 1, tzinfo=TZ) + timedelta(days=rnd.randint(0, 900))
        out.append({
            "merchant_id": f"MER_{i:06d}",
            "merchant_name": f"{rnd.choice(['Shop', 'Cửa hàng', 'Tiệm'])} {rnd.choice(_SHOP_KINDS)} "
                             f"{rnd.choice(_TEN)} {rnd.choice(_TEN)}",
            "merchant_type": mtype, "phone": phone(rnd), "email": f"shop{i:06d}@example.vn",
            "pickup_address": full_address(rnd, ward, provinces[prov]),
            "pickup_province_id": prov, "pickup_ward_id": ward["ward_id"],
            "default_facility_id": facility["facility_id"],
            "contract_type": contract, "discount_pct": discount,
            "payout_cycle": "DAILY" if mtype != "INDIVIDUAL" else rnd.choice(["DAILY", "WEEKLY"]),
            "bank_account_no": f"{rnd.randint(10**11, 10**12 - 1)}",
            "status": "ACTIVE" if rnd.random() > 0.03 else "SUSPENDED",
            "created_at": created, "updated_at": created,
        })

    by_id = {m["merchant_id"]: m for m in out}
    for doc in _DOC_MERCHANTS:
        facility = po_by_prov[doc["pickup_province_id"]][0]["facility_id"]
        by_id[doc["merchant_id"]] = {**out[0], **doc, "email": f"{doc['merchant_id'].lower()}@example.vn",
                                     "default_facility_id": facility, "status": "ACTIVE"}
    return list(by_id.values())


def _insert(cur, table: str, rows: list[dict], conflict: str = "") -> None:
    cols = list(rows[0])
    sql = (f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({', '.join(['%s'] * len(cols))}) "
           f"{conflict}")
    cur.executemany(sql, [[r[c] for c in cols] for r in rows])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dsn", default=os.environ.get("OMS_DSN", DEFAULT_DSN))
    ap.add_argument("--seed", type=int, default=SEED)
    ap.add_argument("--dry-run", action="store_true", help="Chỉ in số dòng, không ghi Postgres")
    args = ap.parse_args()

    merchants = build_merchants(build_catalog(args.seed), args.seed)
    rules, sla = build_pricing_rules(), build_sla_config()
    for name, rows in [("merchants", merchants), ("pricing_rules", rules), ("sla_config", sla)]:
        print(f"  {name:14s} {len(rows):>6,d} rows")
    if args.dry_run:
        return

    import psycopg
    with psycopg.connect(args.dsn) as conn, conn.cursor() as cur:
        _insert(cur, "merchants", merchants, "ON CONFLICT (merchant_id) DO NOTHING")
        _insert(cur, "sla_config", sla, "ON CONFLICT (service_type_id, zone_type) DO NOTHING")
        cur.execute("SELECT count(*) FROM pricing_rules")
        if cur.fetchone()[0] == 0:   # pricing_rules không có khóa tự nhiên → chỉ nạp khi bảng trống
            _insert(cur, "pricing_rules", rules)
    print(f"Done -> {args.dsn}")


if __name__ == "__main__":
    main()
