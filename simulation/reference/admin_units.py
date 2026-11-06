from __future__ import annotations

import csv
import json
import os
from functools import lru_cache

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "reference", "admin_units")

_WARD_TYPES = {"Phường": "PHUONG", "Xã": "XA", "Đặc khu": "DAC_KHU"}

# Viết tắt tiền tố hay gặp trong địa chỉ: "TP HCM", "Q10", "P.10", "TX", "TT" …
_PREFIX_ABBR = {"thanhpho": ["tp"], "tinh": ["t"], "quan": ["q"], "huyen": ["h"], "thixa": ["tx"],
                "phuong": ["p", "f"], "xa": ["x"], "thitran": ["tt"]}


# Địa giới mới (34 tỉnh, 2 cấp) là chuẩn của hệ thống: P79, P79_W26740
def province_id(code: str) -> str:
    return f"P{code}"


def ward_id(province_code: str, ward_code: str) -> str:
    return f"P{province_code}_W{ward_code}"


# Địa giới cũ (63 tỉnh, 3 cấp) chỉ dùng cho địa chỉ cũ: P79_D760, P79_D760_W26740.
# Mã tỉnh cũ trùng số với tỉnh mới nhưng khác phạm vi (P79 cũ chưa gồm Bình Dương, BR-VT).
def legacy_district_id(province_code: str, district_code: str) -> str:
    return f"P{province_code}_D{district_code}"


def legacy_ward_id(province_code: str, district_code: str, ward_code: str) -> str:
    return f"P{province_code}_D{district_code}_W{ward_code}"


def _read(name: str) -> list[dict]:
    with open(os.path.join(DATA_DIR, name), encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


@lru_cache(maxsize=1)
def load() -> dict:
    """Trả về địa giới mới (tỉnh, xã), địa giới cũ (tỉnh, huyện, xã) và ánh xạ xã cũ -> xã mới."""
    provinces, wards = {}, {}
    for r in _read("units_2025.csv"):
        pc = r["provinceCode"]
        provinces.setdefault(pc, {"province_id": province_id(pc), "province_code": pc,
                                  "province_name": r["province"], "province_name_short": r["provinceShort"],
                                  "keywords": json.loads(r["provinceKeywords"])})
        wards[r["wardCode"]] = {"ward_id": ward_id(pc, r["wardCode"]), "ward_code": r["wardCode"],
                                "ward_name": r["ward"], "ward_type": _WARD_TYPES[r["wardType"]],
                                "province_id": province_id(pc),
                                "latitude": float(r["wardLat"]), "longitude": float(r["wardLon"]),
                                "keywords": json.loads(r["wardKeywords"])}

    legacy_provinces, legacy_districts, legacy_wards = {}, {}, []
    for r in _read("units_legacy.csv"):
        pc, dc = r["provinceCode"], r["districtCode"]
        legacy_provinces.setdefault(pc, {"province_id": province_id(pc), "province_name": r["province"],
                                         "keywords": json.loads(r["provinceKeywords"])})
        legacy_districts.setdefault(dc, {"district_id": legacy_district_id(pc, dc),
                                         "district_name": r["district"], "province_code": pc,
                                         "keywords": json.loads(r["districtKeywords"])})
        if r["wardCode"]:  # 5 huyện đảo không có cấp xã
            legacy_wards.append({"ward_id": legacy_ward_id(pc, dc, r["wardCode"]), "ward_code": r["wardCode"],
                                 "ward_name": r["ward"], "district_id": legacy_district_id(pc, dc),
                                 "province_code": pc, "keywords": json.loads(r["wardKeywords"])})

    mapping = {r["old_ward_code"]: (r["new_ward_code"], r["is_divided"] == "true")
               for r in _read("mapping_2025.csv")}
    return {"provinces": provinces, "wards": wards,
            "legacy_provinces": legacy_provinces, "legacy_districts": legacy_districts,
            "legacy_wards": legacy_wards, "mapping_2025": mapping}


@lru_cache(maxsize=1)
def _old_wards_by_new() -> dict[str, list[dict]]:
    u = load()
    out: dict[str, list[dict]] = {}
    for w in u["legacy_wards"]:
        new_code, divided = u["mapping_2025"][w["ward_code"]]
        if not divided:
            out.setdefault(u["wards"][new_code]["ward_id"], []).append(w)
    return out


def old_wards_for(new_ward_id: str) -> list[dict]:
    """Các xã cũ nằm trọn trong xã mới (bỏ xã cũ bị chia) — để sinh địa chỉ viết theo địa giới cũ."""
    return _old_wards_by_new().get(new_ward_id, [])


def expand_aliases(keywords: list[str]) -> list[str]:
    """Từ khóa của bộ dữ liệu (chữ thường, bỏ dấu/khoảng trắng) + các dạng viết tắt tiền tố.

    Chỉ viết tắt "<tiền tố loại><tên>" khi <tên> cũng là một từ khóa, để tên chỉ tình cờ bắt
    đầu bằng cùng chữ cái (vd "Tịnh Biên" → "tinhbien") không bị hiểu nhầm là tiền tố.
    """
    out = list(keywords)
    for kw in keywords:
        for prefix, abbrs in _PREFIX_ABBR.items():
            if kw.startswith(prefix) and kw[len(prefix):] in keywords:
                names = [k for k in keywords if not k.startswith(prefix)]
                out += [a + n for a in abbrs for n in names]
    return list(dict.fromkeys(out))
