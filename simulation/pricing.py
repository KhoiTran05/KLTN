from __future__ import annotations

import math
from datetime import datetime, time, timedelta


def zone_type(sender_ward: dict, receiver_ward: dict) -> str:
    """Vùng giá theo địa giới mới (dòng dim_ward).

    REMOTE: xã nhận là vùng xa (ưu tiên trên mọi vùng khác).
    INNER_CITY: cùng tỉnh và cả hai đầu là phường
    """
    if receiver_ward["is_remote"]:
        return "REMOTE"
    if sender_ward["province_id"] != receiver_ward["province_id"]:
        return "INTER_PROVINCE"
    if sender_ward["ward_type"] == "PHUONG" and receiver_ward["ward_type"] == "PHUONG":
        return "INNER_CITY"
    return "SAME_PROVINCE"


def find_rule(rules: list[dict], service_type_id: str, zone: str, at: datetime) -> dict:
    """Quy tắc giá có hiệu lực tại `at`."""
    return next(r for r in rules
                if r["service_type_id"] == service_type_id and r["zone_type"] == zone
                and r["effective_from"] <= at and (r["effective_to"] is None or at < r["effective_to"]))


def charged_weight(rule: dict, weight_gram: int, length_cm, width_cm, height_cm) -> int:
    """Cân tính cước = max(cân thực, cân quy đổi = D×R×C / volumetric_divisor kg)."""
    if not (length_cm and width_cm and height_cm):
        return weight_gram
    volumetric = math.ceil(length_cm * width_cm * height_cm * 1000 / rule["volumetric_divisor"])
    return max(weight_gram, volumetric)


def quote(rule: dict, zone: str, weight_gram: int, length_cm=None, width_cm=None, height_cm=None,
          declared_value_vnd=None, cod_amount_vnd=0, discount_pct=0.0) -> dict:
    """Báo giá một đơn; tên khóa trùng các cột báo giá của bảng `orders`."""
    cw = charged_weight(rule, weight_gram, length_cm, width_cm, height_cm)
    steps = math.ceil(max(0, cw - rule["first_weight_gram"]) / rule["step_gram"])
    main = rule["first_weight_fee"] + steps * rule["step_fee"]
    fuel = round(main * float(rule["fuel_surcharge_pct"]))
    remote = rule["remote_area_fee"] if zone == "REMOTE" else 0
    insurance = (round(declared_value_vnd * float(rule["insurance_pct"]))
                 if declared_value_vnd and declared_value_vnd > rule["insurance_threshold"] else 0)
    cod_fee = max(round(cod_amount_vnd * float(rule["cod_fee_pct"])), rule["cod_fee_min"]) if cod_amount_vnd > 0 else 0
    discount = round(main * float(discount_pct))
    return {
        "pricing_version": rule["pricing_version"], "zone_type": zone, "charged_weight_gram": cw,
        "main_fee_vnd": main, "fuel_surcharge_vnd": fuel, "remote_area_fee_vnd": remote,
        "insurance_fee_vnd": insurance, "cod_fee_vnd": cod_fee, "discount_vnd": discount,
        "total_fee_vnd": main + fuel + remote + insurance + cod_fee - discount,
    }


def faulty_quote(fault: str, rules: list[dict], service_type_id: str, zone: str, at: datetime, *args) -> dict:
    """Báo giá cố ý sai để đo khả năng phát hiện `FEE_MISMATCH` (chỉ dùng trong mô phỏng).

    `args` giống tham số của `quote` sau `zone`: cân, D, R, C, giá trị khai báo, COD, chiết khấu.
    """
    rule = find_rule(rules, service_type_id, zone, at)
    if fault == "STALE_PRICING_VERSION":
        stale = find_rule(rules, service_type_id, zone, rule["effective_from"] - timedelta(seconds=1))
        return quote(stale, zone, *args)
    q = quote(rule, zone, *args)
    if fault == "MISSING_REMOTE_FEE":
        q["total_fee_vnd"] -= q["remote_area_fee_vnd"]
        q["remote_area_fee_vnd"] = 0
    elif fault == "WRONG_INSURANCE":   # gấp đôi tỉ lệ và bỏ qua ngưỡng → luôn khác phí đúng khi có khai giá
        wrong = round((args[4] or 0) * float(rule["insurance_pct"]) * 2)
        q["total_fee_vnd"] += wrong - q["insurance_fee_vnd"]
        q["insurance_fee_vnd"] = wrong
    return q


def promised_delivery_at(created_at: datetime, sla: dict, time_scale: float = 1.0) -> datetime:
    """Thời hạn giao cam kết = mốc tính + total_hours, nén theo TIME_SCALE.

    Đơn tạo sau `cutoff_time` tính từ 00:00 hôm sau — chỉ áp khi không nén (time_scale = 1),
    vì khi nén một "ngày" chỉ còn vài chục giây thật nên giờ trong ngày không còn ý nghĩa.
    """
    start = created_at
    if time_scale == 1 and created_at.timetz().replace(tzinfo=None) > sla["cutoff_time"]:
        start = datetime.combine(created_at.date() + timedelta(days=1), time(0), created_at.tzinfo)
    return start + timedelta(hours=sla["total_hours"]) / time_scale


def shipment_id(created_at: datetime, seq: int) -> str:
    """Mã vận đơn VTP{yymmdd}{seq:08d}; `seq` lấy từ sequence `shipment_seq` của OMS."""
    return f"VTP{created_at:%y%m%d}{seq:08d}"
