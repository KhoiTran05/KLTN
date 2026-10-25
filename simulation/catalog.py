from __future__ import annotations

import random
from datetime import date, timedelta

import admin_units

SEED = 42

N_DATE_START = date(2018, 1, 1)
N_DATE_DAYS = 6940          
N_PARTNERS = 50
N_SERVICE_TYPES = 20
N_SHIPPERS = 50_000

# 34 tỉnh thành phố sau sáp nhập (07/2025): (gso_code, name_full, name_short, subregion_id, size_weight)
# size_weight quyết định 1 tỉnh thành phố có nhiều hay ít cơ sở facility
_PROVINCES = [
    ("01", "Thành phố Hà Nội", "Hà Nội", "DBSH", 10),
    ("04", "Tỉnh Cao Bằng", "Cao Bằng", "DONG_BAC", 2),
    ("08", "Tỉnh Tuyên Quang", "Tuyên Quang", "DONG_BAC", 4),
    ("11", "Tỉnh Điện Biên", "Điện Biên", "TAY_BAC", 1),
    ("12", "Tỉnh Lai Châu", "Lai Châu", "TAY_BAC", 1),
    ("14", "Tỉnh Sơn La", "Sơn La", "TAY_BAC", 2),
    ("15", "Tỉnh Lào Cai", "Lào Cai", "TAY_BAC", 4),
    ("19", "Tỉnh Thái Nguyên", "Thái Nguyên", "DONG_BAC", 4),
    ("20", "Tỉnh Lạng Sơn", "Lạng Sơn", "DONG_BAC", 2),
    ("22", "Tỉnh Quảng Ninh", "Quảng Ninh", "DONG_BAC", 4),
    ("24", "Tỉnh Bắc Ninh", "Bắc Ninh", "DONG_BAC", 6),
    ("25", "Tỉnh Phú Thọ", "Phú Thọ", "DONG_BAC", 8),
    ("31", "Thành phố Hải Phòng", "Hải Phòng", "DBSH", 9),
    ("33", "Tỉnh Hưng Yên", "Hưng Yên", "DBSH", 6),
    ("37", "Tỉnh Ninh Bình", "Ninh Bình", "DBSH", 7),
    ("38", "Tỉnh Thanh Hóa", "Thanh Hóa", "BAC_TRUNG_BO", 4),
    ("40", "Tỉnh Nghệ An", "Nghệ An", "BAC_TRUNG_BO", 4),
    ("42", "Tỉnh Hà Tĩnh", "Hà Tĩnh", "BAC_TRUNG_BO", 2),
    ("44", "Tỉnh Quảng Trị", "Quảng Trị", "BAC_TRUNG_BO", 4),
    ("46", "Thành phố Huế", "Huế", "BAC_TRUNG_BO", 3),
    ("48", "Thành phố Đà Nẵng", "Đà Nẵng", "NAM_TRUNG_BO", 9),
    ("51", "Tỉnh Quảng Ngãi", "Quảng Ngãi", "NAM_TRUNG_BO", 3),
    ("52", "Tỉnh Gia Lai", "Gia Lai", "NAM_TRUNG_BO", 5),
    ("56", "Tỉnh Khánh Hòa", "Khánh Hòa", "NAM_TRUNG_BO", 4),
    ("66", "Tỉnh Đắk Lắk", "Đắk Lắk", "TAY_NGUYEN", 5),
    ("68", "Tỉnh Lâm Đồng", "Lâm Đồng", "TAY_NGUYEN", 6),
    ("75", "Tỉnh Đồng Nai", "Đồng Nai", "DONG_NAM_BO", 7),
    ("79", "Thành phố Hồ Chí Minh", "TP.HCM", "DONG_NAM_BO", 18),
    ("80", "Tỉnh Tây Ninh", "Tây Ninh", "TAY_NAM_BO", 5),
    ("82", "Tỉnh Đồng Tháp", "Đồng Tháp", "TAY_NAM_BO", 4),
    ("86", "Tỉnh Vĩnh Long", "Vĩnh Long", "TAY_NAM_BO", 5),
    ("91", "Tỉnh An Giang", "An Giang", "TAY_NAM_BO", 6),
    ("92", "Thành phố Cần Thơ", "Cần Thơ", "TAY_NAM_BO", 7),
    ("96", "Tỉnh Cà Mau", "Cà Mau", "TAY_NAM_BO", 3),
]

_REGIONS = [
    ("TAY_BAC", "Tây Bắc Bộ", "TB", "15"),
    ("DONG_BAC", "Đông Bắc Bộ", "DB", "19"),
    ("DBSH", "Đồng bằng sông Hồng", "HH", "01"),
    ("BAC_TRUNG_BO", "Bắc Trung Bộ", "BTB", "40"),
    ("NAM_TRUNG_BO", "Duyên hải Nam Trung Bộ", "NTB", "48"),
    ("TAY_NGUYEN", "Tây Nguyên", "TN", "66"),
    ("DONG_NAM_BO", "Đông Nam Bộ", "DNB", "79"),
    ("TAY_NAM_BO", "Đồng bằng sông Cửu Long", "TNB", "92"),
]

# Mã tỉnh CŨ vùng xa — xã mới thuộc phần đất của các tỉnh này là vùng xa (dim_ward.is_remote)
_REMOTE = {"02", "04", "06", "11", "12", "62", "67", "95", "96"}

_HO = ["Nguyễn", "Trần", "Lê", "Phạm", "Hoàng", "Phan", "Vũ", "Đặng", "Bùi", "Đỗ", "Hồ", "Ngô", "Dương", "Lý"]
_DEM = ["Văn", "Thị", "Hữu", "Đức", "Công", "Quang", "Minh", "Thanh", "Xuân", "Ngọc"]
_TEN = ["An", "Bình", "Cường", "Dũng", "Hà", "Hải", "Hùng", "Khoa", "Lan", "Linh",
        "Long", "Nam", "Phúc", "Quân", "Sơn", "Tâm", "Thắng", "Trang", "Tuấn", "Việt"]

_ITEM_CATEGORIES = ["ELECTRONICS", "FASHION", "COSMETICS", "BOOKS", "FOOD",
                    "HOME_APPLIANCE", "TOYS", "DOCUMENTS", "HEALTH", "OTHER"]
_PARTNER_TYPES = ["ECOMMERCE_PLATFORM", "ENTERPRISE", "RETAIL", "SME"]
_VEHICLES = ["MOTORBIKE", "MOTORBIKE", "MOTORBIKE", "BICYCLE", "VAN", "ON_FOOT"]


def _vn_name(rnd: random.Random) -> str:
    return f"{rnd.choice(_HO)} {rnd.choice(_DEM)} {rnd.choice(_TEN)}"


def build_catalog(seed: int = SEED) -> dict:
    """Trả về mọi bảng dim dưới dạng list các dict. Cùng seed thì cùng kết quả."""
    rnd = random.Random(seed)

    regions = [
        {"region_id": rid, "region_name": rname, "region_code": rcode,
         "headquarter_province_id": f"P{hq}"}
        for rid, rname, rcode, hq in _REGIONS
    ]

    provinces, branches, facilities, wards, shippers = [], [], [], [], []
    units = admin_units.load()
    remote_wards = {units["mapping_2025"][w["ward_code"]][0] for w in units["legacy_wards"]
                    if w["province_code"] in _REMOTE}
    wards_by_province: dict[str, list[dict]] = {}
    for w in units["wards"].values():
        wards_by_province.setdefault(w["province_id"], []).append(w)
    facility_seq = 0
    branch_seq = 0

    for code, name_full, name_short, region_id, weight in _PROVINCES:
        pid = f"P{code}"
        prov_wards = wards_by_province[pid]
        is_remote = all(w["ward_code"] in remote_wards for w in prov_wards)
        provinces.append({
            "province_id": pid, "province_code": code, "province_name": name_full,
            "province_name_short": name_short, "region_id": region_id,
            "is_remote": is_remote, "created_at": "2018-01-01T00:00:00",
        })

        # Branches
        n_branch = max(1, round(weight / 1.8))
        prov_branches = []
        for _ in range(n_branch):
            branch_seq += 1
            bid = f"CN_{pid}_{branch_seq:03d}"
            branches.append({
                "branch_id": bid, "branch_name": f"Chi nhánh {name_short} {branch_seq:03d}",
                "branch_code": f"{code}{branch_seq:02d}", "region_id": region_id,
                "province_id": pid,
                "branch_type": "CITY" if weight >= 6 else ("PROVINCE" if weight >= 3 else "CLUSTER"),
                "manager_name": _vn_name(rnd), "is_active": True,
                "created_at": "2018-03-15T00:00:00",
            })
            prov_branches.append(bid)

        # Wards (địa giới mới, không còn cấp huyện)
        for w in prov_wards:
            wards.append({
                "ward_id": w["ward_id"], "ward_code": w["ward_code"],
                "ward_name": w["ward_name"], "ward_type": w["ward_type"], "province_id": pid,
                "is_remote": w["ward_code"] in remote_wards,
                # dữ liệu chính thức không có mã bưu chính — vẫn giả lập
                "post_code": f"{code}{w['ward_code'][-4:]}",
                "latitude": w["latitude"], "longitude": w["longitude"],
            })

        # Facilities: post offices và hubs cho weight >= 4
        n_po = max(8, weight * 11)
        for _ in range(n_po):
            facility_seq += 1
            fid = f"BC_{pid}_{facility_seq:04d}"
            ward = rnd.choice(prov_wards)
            facilities.append({
                "facility_id": fid, "facility_name": f"Bưu cục {name_short} {facility_seq:04d}",
                "facility_code": f"{code}_{facility_seq:04d}", "facility_type": "POST_OFFICE",
                "branch_id": rnd.choice(prov_branches), "province_id": pid,
                "ward_id": ward["ward_id"],
                "address": f"Số {rnd.randint(1, 300)} đường {rnd.randint(1, 50)}, {ward['ward_name']}",
                "latitude": ward["latitude"], "longitude": ward["longitude"],
                "capacity_per_day": rnd.choice([7, 8, 9, 10]),
                "is_active": True, "open_time": "07:30:00", "close_time": "21:00:00",
            })

        n_hub = 2 if weight >= 8 else (1 if weight >= 4 else 0)
        for h in range(1, n_hub + 1):
            facility_seq += 1
            fid = f"HUB_{pid}_{h:02d}"
            ward = next(w for w in prov_wards if w["ward_type"] == "PHUONG")
            facilities.append({
                "facility_id": fid, "facility_name": f"Trung tâm khai thác {name_short} {h:02d}",
                "facility_code": f"HUB_{code}_{h:02d}", "facility_type": "HUB",
                "branch_id": prov_branches[0], "province_id": pid,
                "ward_id": ward["ward_id"],
                "address": f"KCN {name_short}, lô {h}",
                "latitude": ward["latitude"], "longitude": ward["longitude"],
                "capacity_per_day": rnd.choice([7, 8, 9, 10]),
                "is_active": True, "open_time": "00:00:00", "close_time": "23:59:00",
            })

    # Mỗi tỉnh cần ít nhâ 1 HUB để mô phỏng hành trình vận đơn - nếu chưa tồn tại HUB
    # -> lấy bưu cụ đầu tiên làm HUB
    hubs = [f for f in facilities if f["facility_type"] == "HUB"]
    hub_provinces = {f["province_id"] for f in hubs}
    for f in facilities:
        if f["facility_type"] == "POST_OFFICE" and f["province_id"] not in hub_provinces:
            f["facility_type"] = "HUB"
            f["facility_name"] = f["facility_name"].replace("Bưu cục", "Trung tâm khai thác")
            hub_provinces.add(f["province_id"])
            hubs.append(f)

    post_offices = [f for f in facilities if f["facility_type"] == "POST_OFFICE"]

    # dim_service_type
    service_types = _build_service_types()

    # dim_partner
    partners = _build_partners(rnd)

    # dim_route
    routes = _build_routes(rnd, hubs)

    # dim_shipper
    for i in range(1, N_SHIPPERS + 1):
        f = post_offices[i % len(post_offices)]
        prov = f["province_id"]
        shippers.append({
            "shipper_id": f"SHP_{prov}_{i:06d}", "shipper_code": f"{prov}_K{i:06d}",
            "full_name": _vn_name(rnd), "facility_id": f["facility_id"],
            "vehicle_type": rnd.choice(_VEHICLES),
            "vehicle_plate": f"{rnd.randint(11, 99)}{rnd.choice('ABCDEFGH')}{rnd.randint(1,9)}-{rnd.randint(10000,99999)}",
            "phone": f"09{rnd.randint(10,99)}****{rnd.randint(10,99)}",
            "join_date": (date(2019, 1, 1) + timedelta(days=rnd.randint(0, 2000))).isoformat(),
            "is_active": rnd.random() > 0.05,
            "avg_daily_capacity": rnd.randint(25, 60),
        })

    dates = _build_dates()

    return {
        "dim_region": regions,
        "dim_province": provinces,
        "dim_ward": wards,
        "dim_branch": branches,
        "dim_facility": facilities,
        "dim_service_type": service_types,
        "dim_route": routes,
        "dim_partner": partners,
        "dim_shipper": shippers,
        "dim_date": dates,
    }


def _build_service_types() -> list[dict]:
    base = [
        ("SAMEDAY", "Giao trong ngày", "SD", "SAMEDAY", 0, 1, 1, 2, 60000),
        ("EXPRESS", "Chuyển phát nhanh", "EXP", "EXPRESS", 1, 1, 2, 4, 35000),
        ("NEXTDAY", "Giao hôm sau", "ND", "NEXTDAY", 1, 1, 2, 3, 30000),
        ("STANDARD", "Tiêu chuẩn", "STD", "STANDARD", 2, 2, 4, 6, 22000),
        ("ECONOMY", "Tiết kiệm", "ECO", "ECONOMY", 3, 3, 5, 8, 16000),
    ]
    out = []
    for i in range(N_SERVICE_TYPES):
        code, name, scode, tier, c, sp, ip, rm, price = base[i % len(base)]
        suffix = "" if i < len(base) else f"_{i // len(base)}"
        out.append({
            "service_type_id": code + suffix, "service_name": name + (suffix and f" {suffix}"),
            "service_code": scode + suffix, "speed_tier": tier,
            "sla_inner_city_days": c, "sla_same_province_days": sp,
            "sla_inter_province_days": ip, "sla_remote_days": rm,
            "max_weight_kg": 30.0, "max_size_cm3": 500000,
            "supports_cod": True, "base_price_vnd": price, "is_active": True,
        })
    return out


def _build_partners(rnd: random.Random) -> list[dict]:
    named = ["SHOPEE", "LAZADA", "TIKI", "TIKTOK_SHOP", "SENDO", "RETAIL"]
    out = []
    for i in range(N_PARTNERS):
        pid = named[i] if i < len(named) else f"PARTNER_{i:03d}"
        ptype = "ECOMMERCE_PLATFORM" if i < len(named) - 1 else rnd.choice(_PARTNER_TYPES)
        out.append({
            "partner_id": pid, "partner_name": pid.title().replace("_", " "),
            "partner_type": ptype,
            "contract_type": rnd.choice(["VOLUME", "FIXED", "PAY_PER_USE"]),
            "discount_rate": round(rnd.uniform(0.0, 0.25), 4),
            "api_integration": ptype == "ECOMMERCE_PLATFORM",
            "contact_email": f"logistics@{pid.lower()}.com", "is_active": True,
        })
    return out


def _build_routes(rnd: random.Random, hubs: list[dict], target: int = 500) -> list[dict]:
    out = []
    seq = 0
    pairs = [(o, d) for o in hubs for d in hubs if o["facility_id"] != d["facility_id"]]
    rnd.shuffle(pairs)
    for o, d in pairs[:target]:
        seq += 1
        mode = rnd.choice(["ROAD_TRUCK", "ROAD_TRUCK", "AIR", "RAIL"])
        dist = round(rnd.uniform(30, 1700), 2)
        dur = round(dist / (500 if mode == "AIR" else 50), 2)
        out.append({
            "route_id": f"LH_{o['province_id']}_{d['province_id']}_{seq:04d}",
            "route_name": f"{o['facility_name']} to {d['facility_name']}",
            "origin_hub_id": o["facility_id"], "destination_hub_id": d["facility_id"],
            "transport_mode": mode, "distance_km": dist,
            "estimated_duration_hours": dur,
            "departure_times": rnd.choice(["06:00:00", "12:00:00", "18:00:00"]),
            "frequency_per_day": rnd.choice([1, 2, 3, 4]),
            "carrier_name": rnd.choice(["Nội bộ", "Vietnam Airlines Cargo", "Đường sắt VN"]),
            "is_active": True, "effective_from": "2023-01-01", "effective_to": None,
        })
    return out


def _build_dates() -> list[dict]:
    fixed_holidays = {(1, 1): "Tết Dương lịch", (4, 30): "Giải phóng miền Nam",
                      (5, 1): "Quốc tế Lao động", (9, 2): "Quốc khánh"}
    names = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
    months = ["January", "February", "March", "April", "May", "June",
              "July", "August", "September", "October", "November", "December"]
    out = []
    for i in range(N_DATE_DAYS):
        d = N_DATE_START + timedelta(days=i)
        dow = d.weekday()  # 0 = thu 2
        is_weekend = dow >= 5
        holiday = fixed_holidays.get((d.month, d.day))
        out.append({
            "date_id": int(d.strftime("%Y%m%d")), "full_date": d.isoformat(),
            "day_of_week": dow + 1, "day_name": names[dow], "day_of_month": d.day,
            "month_no": d.month, "month_name": months[d.month - 1],
            "year_no": d.year, "quarter_no": (d.month - 1) // 3 + 1,
            "is_weekend": is_weekend, "is_holiday": holiday is not None,
            "holiday_name": holiday,
            "is_working_day": (not is_weekend) and (holiday is None),
        })
    return out


if __name__ == "__main__":
    cat = build_catalog()
    for name, rows in cat.items():
        print(f"{name:18s} {len(rows):>7,d} rows")
