from __future__ import annotations

import re
import unicodedata

from simulation.reference.reference import build_reference


def normalize(text: str) -> str:
    """Về dạng khóa của ref_address_alias: chữ thường, bỏ dấu, bỏ khoảng trắng và dấu câu."""
    text = unicodedata.normalize("NFD", text.lower().replace("đ", "d"))
    return re.sub(r"[^a-z0-9]", "", "".join(c for c in text if not unicodedata.combining(c)))


def _accented_key(text: str) -> str:
    """Khóa còn dấu: dữ liệu giữ dấu trong alias của các xã chỉ khác nhau ở dấu (Minh Quán / Minh Quân)."""
    return re.sub(r"[\W_]", "", unicodedata.normalize("NFC", text.lower()))


class AddressLookup:
    """Tra (tỉnh, huyện, xã) dạng văn bản, viết theo địa giới cũ hoặc mới, ra ID địa giới mới."""

    def __init__(self):
        ref = build_reference()
        self._alias: dict[str, dict[str, set[str]]] = {}
        for a in ref["ref_address_alias"]:
            self._alias.setdefault(a["level"], {}).setdefault(a["alias"], set()).add(a["target_id"])
        self._new_ward = {m["old_ward_id"]: m["new_ward_id"] for m in ref["ref_admin_unit_mapping"]}
        self._new_province = {m["old_province_id"]: m["new_province_id"] for m in ref["ref_admin_unit_mapping"]}

    def _ids(self, level: str, text: str | None) -> set[str]:
        return self._alias[level].get(normalize(text), set()) if text else set()

    def _ward_ids(self, level: str, text: str | None, keep) -> set[str]:
        """Xã thỏa `keep`: khớp đúng cả dấu thì lấy trước, không có mới khớp theo dạng bỏ dấu."""
        if not text:
            return set()
        accented = {w for w in self._alias[level].get(_accented_key(text), ()) if keep(w)}
        return accented or {w for w in self._ids(level, text) if keep(w)}

    def resolve(self, province: str, district: str | None = None, ward: str | None = None):
        """Trả về (province_id, ward_id) mới; ward_id = None nếu không có xã hoặc nhiều ứng viên."""
        provinces = self._ids("PROVINCE", province) | {
            self._new_province[p] for p in self._ids("PROVINCE_LEGACY", province)}
        if not provinces:
            return None, None
        province_id = next(iter(provinces))   # tên tỉnh cũ và mới trùng nhau luôn trỏ về cùng một tỉnh mới

        def in_province(ward_id):
            return ward_id.startswith(province_id + "_")

        districts = self._ids("DISTRICT_LEGACY", district)

        def in_old_scope(old_ward_id):
            return in_province(self._new_ward[old_ward_id]) and (
                not districts or old_ward_id.rsplit("_W", 1)[0] in districts)

        new_wards = self._ward_ids("WARD", ward, in_province)
        old_wards = self._ward_ids("WARD_LEGACY", ward, in_old_scope)
        # tên huyện có thể trùng giữa các tỉnh cũ đã nhập chung (Châu Thành ở Bến Tre, Trà Vinh → Vĩnh Long)
        old_provinces = self._ids("PROVINCE_LEGACY", province)
        old_wards = {w for w in old_wards if w.split("_D")[0] in old_provinces} or old_wards
        mapped = {self._new_ward[w] for w in old_wards}

        # có cấp huyện nghĩa là địa chỉ viết theo địa giới cũ → ưu tiên tra tên cũ
        candidates = (mapped or new_wards) if district else (new_wards or mapped)
        return province_id, next(iter(candidates)) if len(candidates) == 1 else None
