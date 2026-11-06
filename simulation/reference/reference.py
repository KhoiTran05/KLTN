"""Các bảng tham chiếu S9 (ref_*), xem docs/data_samples.md §9."""
from __future__ import annotations

import admin_units

# (from_state, event_type, to_state, phase). from_state None = chưa có trạng thái;
# from_state "*" = mọi trạng thái, to_state "*" = giữ nguyên trạng thái.
_TRANSITIONS = [
    (None, "order_created", "CREATED", "ORDER"),
    ("CREATED", "order_cancelled", "CANCELLED", "ORDER"),
    ("CREATED", "pickup_task_assigned", "PICKUP_ASSIGNED", "FIRST_MILE"),
    ("PICKUP_ASSIGNED", "pickup_failed", "PICKUP_ASSIGNED", "FIRST_MILE"),
    ("PICKUP_ASSIGNED", "picked_up", "PICKED_UP", "FIRST_MILE"),
    ("PICKED_UP", "arrived_at_origin_post_office", "AT_ORIGIN_PO", "FIRST_MILE"),
    ("AT_ORIGIN_PO", "departed_origin_post_office", "IN_TRANSIT", "MIDDLE_MILE"),
    ("IN_TRANSIT", "arrived_at_hub", "AT_HUB", "MIDDLE_MILE"),
    ("AT_HUB", "sorted_at_hub", "SORTED", "MIDDLE_MILE"),
    ("SORTED", "departed_hub", "IN_TRANSIT", "MIDDLE_MILE"),
    ("IN_TRANSIT", "arrived_at_destination_post_office", "AT_DEST_PO", "LAST_MILE"),
    ("AT_DEST_PO", "dispatched_for_delivery", "OUT_FOR_DELIVERY", "LAST_MILE"),
    ("OUT_FOR_DELIVERY", "delivered", "DELIVERED", "LAST_MILE"),
    ("OUT_FOR_DELIVERY", "failed_delivery", "DELIVERY_FAILED", "LAST_MILE"),
    ("DELIVERY_FAILED", "dispatched_for_delivery", "OUT_FOR_DELIVERY", "LAST_MILE"),
    ("DELIVERY_FAILED", "return_initiated", "RETURNING", "RETURN"),
    ("RETURNING", "returned_to_sender", "RETURNED", "RETURN"),
    ("*", "exception_reported", "*", "ANY"),
]

# (reason_code, reason_name_vi, category, is_customer_fault)
_FAILURE_REASONS = [
    ("RECEIVER_ABSENT", "Người nhận vắng nhà", "RECEIVER", True),
    ("PHONE_NOT_ANSWERED", "Không liên lạc được", "RECEIVER", True),
    ("WRONG_ADDRESS", "Sai địa chỉ", "SENDER", True),
    ("RECEIVER_REFUSED", "Từ chối nhận", "RECEIVER", True),
    ("DAMAGED_PACKAGE", "Hàng hư hỏng", "CARRIER", False),
    ("OUTSIDE_DELIVERY_HOURS", "Ngoài giờ giao", "CARRIER", False),
    # pickup_failed (S5)
    ("SENDER_ABSENT", "Người gửi vắng mặt", "SENDER", True),
    ("GOODS_NOT_READY", "Hàng chưa sẵn sàng", "SENDER", True),
    ("PROHIBITED_ITEM", "Hàng cấm gửi", "SENDER", True),
]


def build_reference() -> dict:
    """Trả về mọi bảng ref_* dưới dạng list các dict."""
    units = admin_units.load()
    wards = units["wards"]
    legacy_provinces, legacy_districts = units["legacy_provinces"], units["legacy_districts"]

    mapping = []
    for w in units["legacy_wards"]:
        d = legacy_districts[w["district_id"].split("_D")[1]]
        new_code, divided = units["mapping_2025"][w["ward_code"]]
        new = wards[new_code]
        mapping.append({
            "old_province_id": admin_units.province_id(w["province_code"]),
            "old_province_name": legacy_provinces[w["province_code"]]["province_name"],
            "old_district_id": w["district_id"], "old_district_name": d["district_name"],
            "old_ward_id": w["ward_id"], "old_ward_name": w["ward_name"],
            "new_province_id": new["province_id"], "new_ward_id": new["ward_id"],
            "new_ward_name": new["ward_name"],
            "is_divided": divided,  # xã cũ bị chia cho nhiều xã mới
        })

    aliases = []

    def add(level, target_id, target_name, keywords):
        aliases.extend({"alias": a, "level": level, "target_id": target_id, "target_name": target_name}
                       for a in admin_units.expand_aliases(keywords))

    # địa giới mới: target_id là ID của dim_province / dim_ward
    for p in units["provinces"].values():
        add("PROVINCE", p["province_id"], p["province_name"], p["keywords"])
    for w in wards.values():
        add("WARD", w["ward_id"], w["ward_name"], w["keywords"])
    # địa giới cũ: target_id là old_*_id trong ref_admin_unit_mapping
    for p in legacy_provinces.values():
        add("PROVINCE_LEGACY", p["province_id"], p["province_name"], p["keywords"])
    for d in legacy_districts.values():
        add("DISTRICT_LEGACY", d["district_id"], d["district_name"], d["keywords"])
    for w in units["legacy_wards"]:
        add("WARD_LEGACY", w["ward_id"], w["ward_name"], w["keywords"])

    return {
        "ref_status_transition": [
            {"from_state": f, "event_type": e, "to_state": t, "phase": ph} for f, e, t, ph in _TRANSITIONS],
        "ref_failure_reason": [
            {"reason_code": c, "reason_name_vi": n, "category": cat, "is_customer_fault": cf}
            for c, n, cat, cf in _FAILURE_REASONS],
        "ref_admin_unit_mapping": mapping,
        "ref_address_alias": aliases,
    }


if __name__ == "__main__":
    for name, rows in build_reference().items():
        print(f"{name:24s} {len(rows):>7,d} rows")
