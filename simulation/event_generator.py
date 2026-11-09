#!/usr/bin/env python3
import argparse
import heapq
import itertools
import os
import random
import time
from datetime import datetime, timezone

from simulation import pricing
from simulation.channels import OmsChannel, PartnerChannel, StdoutOmsChannel, StdoutPartnerChannel
from simulation.oms_seed import (DEFAULT_DSN, SERVICES, TZ, build_merchants, build_pricing_rules, build_sla_config,
                                 full_address, phone, street_address)
from simulation.reference import admin_units
from simulation.reference.admin_units import old_wards_for
from simulation.reference.catalog import _vn_name, build_catalog

_SERVICE_WEIGHTS = [5, 30, 10, 40, 15]   # theo thứ tự SERVICES
_SHOPEE_SERVICE_CODE = {"SAMEDAY": "SD", "EXPRESS": "EXP", "NEXTDAY": "ND", "STANDARD": "STD", "ECONOMY": "ECO"}
_ITEMS = {
    "COSMETICS": ["Bộ dưỡng da 3 món", "Son dưỡng môi", "Nước hoa mini", "Kem chống nắng"],
    "FASHION": ["Áo thun", "Quần jean", "Váy liền", "Giày thể thao"],
    "ELECTRONICS": ["Tai nghe bluetooth", "Sạc dự phòng", "Chuột không dây", "Loa mini"],
    "HOME_APPLIANCE": ["Nồi chiên không dầu mini", "Máy xay sinh tố", "Bình giữ nhiệt"],
    "BOOKS": ["Sách kỹ năng", "Truyện tranh", "Giáo trình"],
    "TOYS": ["Bộ lắp ghép", "Gấu bông", "Xe điều khiển"],
    "FOOD": ["Cà phê rang xay", "Hạt điều", "Trà ô long"],
    "HEALTH": ["Vitamin tổng hợp", "Khẩu trang y tế", "Máy đo huyết áp"],
}
_FRAGILE = {"COSMETICS", "ELECTRONICS", "HOME_APPLIANCE"}
_CANCEL_REASONS = ["MERCHANT_REQUEST", "OUT_OF_STOCK", "CUSTOMER_CANCELLED", "DUPLICATE_ORDER"]
_DELIVERY_NOTES = [None, None, "Giao giờ hành chính", "Gọi trước khi giao", "Cho xem hàng"]


class Refs:
    def __init__(self, rnd: random.Random):
        cat = build_catalog()
        self.rnd = rnd
        self.provinces = {p["province_id"]: p for p in cat["dim_province"]}
        self.wards = {w["ward_id"]: w for w in cat["dim_ward"]}
        self.wards_by_prov: dict[str, list[dict]] = {}
        for w in cat["dim_ward"]:
            self.wards_by_prov.setdefault(w["province_id"], []).append(w)

        self.po_by_prov: dict[str, list[str]] = {}
        self.po_by_ward: dict[str, list[str]] = {}
        for f in cat["dim_facility"]:
            if f["facility_type"] == "POST_OFFICE":
                self.po_by_prov.setdefault(f["province_id"], []).append(f["facility_id"])
                self.po_by_ward.setdefault(f["ward_id"], []).append(f["facility_id"])
        self.order_provs = list(self.po_by_prov)
        self.order_weights = [len(self.po_by_prov[p]) for p in self.order_provs]

        self.merchants = [m for m in build_merchants(cat) if m["status"] == "ACTIVE"]
        self.rules = build_pricing_rules()
        self.sla = {(s["service_type_id"], s["zone_type"]): s for s in build_sla_config()}
        self._order_ref_seq: dict[str, itertools.count] = {}

    def pick_province(self) -> str:
        return self.rnd.choices(self.order_provs, weights=self.order_weights, k=1)[0]

    def pick_po(self, ward: dict) -> str:
        """Bưu cục phát: ưu tiên bưu cục cùng xã, không có thì bưu cục bất kỳ trong tỉnh."""
        return self.rnd.choice(self.po_by_ward.get(ward["ward_id"]) or self.po_by_prov[ward["province_id"]])

    def next_order_ref(self, merchant_id: str, now: datetime) -> str:
        seq = self._order_ref_seq.setdefault(merchant_id, itertools.count(1))
        return f"{merchant_id[-4:]}-{now:%Y%m%d}-{next(seq):04d}"


def _hours(rnd, lo, hi):
    """Một độ trễ trong [lo, hi] giờ, đổi ra giây (thời gian mô phỏng, trước khi nén)."""
    return rnd.uniform(lo, hi) * 3600.0


def _pick_receiver_ward(refs: Refs, rnd: random.Random, merchant: dict) -> dict:
    prov = merchant["pickup_province_id"] if rnd.random() < 0.3 else refs.pick_province()
    return rnd.choice(refs.wards_by_prov[prov])


def _pick_goods(rnd: random.Random) -> tuple:
    """(dịch vụ, ngành hàng, cân gram, (D, R, C), giá trị khai báo, COD)."""
    dims = (rnd.randint(10, 50), rnd.randint(10, 40), rnd.randint(5, 30)) if rnd.random() < 0.8 else (None,) * 3
    declared = rnd.randint(50, 3_000) * 1000
    return (rnd.choices(SERVICES, weights=_SERVICE_WEIGHTS, k=1)[0], rnd.choice(list(_ITEMS)),
            rnd.choice([300, 500, 800, 1000, 1200, 1500, 2000, 3000, 5000]), dims,
            declared, declared if rnd.random() < 0.7 else 0)


def plan_oms_order(refs: Refs, rnd: random.Random, now: datetime, scale: float,
                   update_pct: float, cancel_pct: float) -> tuple[dict, list[tuple[float, dict]]]:
    """Đơn OMS (chưa có shipment_id) + các UPDATE về sau: [(offset giây mô phỏng, cột thay đổi)]."""
    m = rnd.choice(refs.merchants)
    sender_ward = refs.wards[m["pickup_ward_id"]]
    receiver_ward = _pick_receiver_ward(refs, rnd, m)
    receiver_prov = receiver_ward["province_id"]
    service, category, weight, dims, declared, cod = _pick_goods(rnd)

    zone = pricing.zone_type(sender_ward, receiver_ward)
    rule = pricing.find_rule(refs.rules, service, zone, now)
    sla = refs.sla[(service, zone)]
    order = {
        "merchant_id": m["merchant_id"], "merchant_order_ref": refs.next_order_ref(m["merchant_id"], now),
        "source_channel": rnd.choice(["OMS_WEB", "OMS_WEB", "OMS_APP"]),
        "service_type_id": service, "status": "CREATED",
        "sender_name": m["merchant_name"], "sender_phone": m["phone"], "sender_address": m["pickup_address"],
        "sender_province_id": m["pickup_province_id"], "sender_ward_id": m["pickup_ward_id"],
        "pickup_facility_id": m["default_facility_id"],
        "receiver_name": _vn_name(rnd), "receiver_phone": phone(rnd),
        "receiver_address": full_address(rnd, receiver_ward, refs.provinces[receiver_prov]),
        "receiver_province_id": receiver_prov, "receiver_ward_id": receiver_ward["ward_id"],
        "delivery_facility_id": refs.pick_po(receiver_ward),
        "item_description": rnd.choice(_ITEMS[category]), "item_category": category,
        "item_quantity": rnd.randint(1, 3), "weight_gram": weight,
        "length_cm": dims[0], "width_cm": dims[1], "height_cm": dims[2],
        "is_fragile": category in _FRAGILE and rnd.random() < 0.5,
        "declared_value_vnd": declared, "cod_amount_vnd": cod,
        "fee_payer": "SENDER" if rnd.random() < 0.7 else "RECEIVER",
        **pricing.quote(rule, zone, weight, *dims, declared, cod, m["discount_pct"]),
        "promised_delivery_at": pricing.promised_delivery_at(now, sla, scale),
        "pickup_note": None, "delivery_note": rnd.choice(_DELIVERY_NOTES), "cancel_reason": None,
        "created_at": now, "updated_at": now,
    }

    updates = []
    if rnd.random() < cancel_pct:   # hủy trước khi lấy hàng → vòng đời dừng
        updates.append((_hours(rnd, 0.1, 0.9 * sla["pickup_hours"]),
                        {"status": "CANCELLED", "cancel_reason": rnd.choice(_CANCEL_REASONS)}))
    elif rnd.random() < update_pct:  # đổi SĐT hoặc số nhà người nhận (cùng xã → không đổi cước)
        if rnd.random() < 0.5:
            change = {"receiver_phone": phone(rnd)}
        else:
            change = {"receiver_address": order["receiver_address"].replace(
                order["receiver_address"].split(", ")[0], street_address(rnd), 1)}
        updates.append((_hours(rnd, 0.05 * sla["total_hours"], 0.6 * sla["total_hours"]), change))
    return order, updates


def _partner_address(refs: Refs, rnd: random.Random, street: str, ward: dict, legacy_pct: float) -> dict:
    """Địa chỉ gửi qua S2: viết theo địa giới mới, hoặc theo địa giới cũ nếu xã mới có xã cũ không bị chia."""
    old_wards = old_wards_for(ward["ward_id"])
    if old_wards and rnd.random() < legacy_pct:
        old, units = rnd.choice(old_wards), admin_units.load()
        district = units["legacy_districts"][old["district_id"].split("_D")[1]]["district_name"]
        province = units["legacy_provinces"][old["province_code"]]["province_name"]
        return {"line1": street, "ward": old["ward_name"], "district": district, "province": province,
                "full": f"{street}, {old['ward_name']}, {district}, {province}"}
    province = refs.provinces[ward["province_id"]]["province_name_short"]
    return {"line1": street, "ward": ward["ward_name"], "district": None, "province": province,
            "full": f"{street}, {ward['ward_name']}, {province}"}


def _partner_phone(rnd: random.Random, number: str) -> str:
    """Đối tác không chuẩn hóa SĐT: có thể có khoảng trắng hoặc đầu +84."""
    return rnd.choice([number, f"{number[:4]} {number[4:7]} {number[7:]}",
                       f"+84 {number[1:4]} {number[4:7]} {number[7:]}"])


def plan_partner_order(refs: Refs, rnd: random.Random, now: datetime, legacy_pct: float) -> tuple[str, dict]:
    """(đối tác, body request) theo schema riêng của Shopee / TikTok Shop (docs/data_samples.md §2.1–§2.2)."""
    m = rnd.choice(refs.merchants)
    receiver_ward = _pick_receiver_ward(refs, rnd, m)
    service, category, weight, dims, declared, cod = _pick_goods(rnd)
    item, qty = rnd.choice(_ITEMS[category]), rnd.randint(1, 3)
    sender = _partner_address(refs, rnd, m["pickup_address"].rsplit(", ", 2)[0], refs.wards[m["pickup_ward_id"]], legacy_pct)
    receiver = _partner_address(refs, rnd, street_address(rnd), receiver_ward, legacy_pct)
    receiver_name, buyer_pays = _vn_name(rnd), rnd.random() < 0.3

    if rnd.random() < 0.5:
        return "shopee", {
            "order_sn": f"{now:%y%m%d}{rnd.randbytes(3).hex().upper()}",
            "shop": {"shop_id": int(m["merchant_id"][-6:]), "merchant_code": m["merchant_id"]},
            "create_time": int(now.timestamp()), "service_code": _SHOPEE_SERVICE_CODE[service],
            "pickup": {"name": m["merchant_name"], "phone": _partner_phone(rnd, m["phone"]), "full_address": sender["full"]},
            "recipient": {"name": receiver_name, "phone": _partner_phone(rnd, phone(rnd)), "full_address": receiver["full"],
                          "city": receiver["province"], "district": receiver["district"], "ward": receiver["ward"]},
            "parcel": {"weight_kg": weight / 1000,
                       "dimension_cm": {"l": dims[0], "w": dims[1], "h": dims[2]} if dims[0] else None,
                       "items": [{"name": item, "qty": qty, "price": declared // qty}]},
            "cod_amount": cod, "item_value": declared, "fee_paid_by": "buyer" if buyer_pays else "seller",
        }

    def money(amount):
        return {"amount": str(amount), "currency": "VND"}

    def address(a):
        return {"line1": a["line1"], "ward": a["ward"], "district": a["district"], "province": a["province"]}

    return "tiktok", {
        "orderId": str(rnd.randint(10 ** 14, 10 ** 15 - 1)), "sellerId": m["merchant_id"],
        "createdAt": now.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "shippingService": service,
        "sender": {"contactName": m["merchant_name"], "contactPhone": _partner_phone(rnd, m["phone"]), "address": address(sender)},
        "receiver": {"contactName": receiver_name, "contactPhone": _partner_phone(rnd, phone(rnd)), "address": address(receiver)},
        "package": {"weightGram": str(weight), "lengthCm": dims[0], "widthCm": dims[1], "heightCm": dims[2]},
        "items": [{"skuName": item, "quantity": qty, "unitPrice": money(declared // qty)}],
        "codAmount": money(cod), "declaredValue": money(declared), "payer": "BUYER" if buyer_pays else "SELLER",
    }


def run(oms, partner, refs, rnd, rate, duration, scale, update_pct, cancel_pct, partner_share, legacy_pct):
    """Bộ lập lịch theo giờ thật: mỗi đơn tạo ngay, các UPDATE đặt tại created_wall + offset/scale."""
    heap = []  # (emit_wall, tie, shipment_id, fields)
    tie = itertools.count()
    start = time.time()
    next_create = start
    create_interval = 1.0 / rate
    created = updated = partner_accepted = partner_rejected = 0
    accepting = True

    while True:
        now = time.time()

        if accepting and duration and (now - start) >= duration:
            accepting = False
        if accepting and now >= next_create:
            now_dt = datetime.fromtimestamp(now, TZ)
            if rnd.random() < partner_share:
                res = partner.post_order(*plan_partner_order(refs, rnd, now_dt, legacy_pct))
                if res["status"] == "ACCEPTED":
                    partner_accepted += 1
                else:
                    partner_rejected += 1
            else:
                order, updates = plan_oms_order(refs, rnd, now_dt, scale, update_pct, cancel_pct)
                sid = oms.next_shipment_id(now_dt)
                oms.insert_order({"shipment_id": sid, **order})
                created += 1
                for offset, fields in updates:
                    heapq.heappush(heap, (now + offset / scale, next(tie), sid, fields))
            next_create += create_interval

        while heap and heap[0][0] <= now:
            emit_wall, _, sid, fields = heapq.heappop(heap)
            oms.update_order(sid, {**fields, "updated_at": datetime.fromtimestamp(emit_wall, TZ)})
            updated += 1

        if not accepting and not heap:   # chờ hết các UPDATE đã lên lịch rồi mới dừng
            break
        time.sleep(0.005)

    oms.close()
    partner.close()
    print(f"Done. oms_created={created} oms_updated={updated} partner_accepted={partner_accepted} "
          f"partner_rejected={partner_rejected} in {time.time()-start:.0f}s")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rate", type=float, default=2.0, help="Đơn tạo mỗi giây")
    ap.add_argument("--duration", type=int, default=600, help="Số giây tạo đơn (0 = vô hạn)")
    ap.add_argument("--time-scale", type=float, default=2000.0, help="Hệ số nén thời gian vòng đời")
    ap.add_argument("--update-pct", type=float, default=0.05, help="Tỉ lệ đơn bị sửa SĐT / địa chỉ")
    ap.add_argument("--cancel-pct", type=float, default=0.03, help="Tỉ lệ đơn bị hủy trước lấy hàng")
    ap.add_argument("--partner-share", type=float, default=0.4, help="Tỉ lệ đơn đi qua S2 Partner API")
    ap.add_argument("--legacy-pct", type=float, default=0.3, help="Tỉ lệ địa chỉ S2 viết theo địa giới cũ")
    ap.add_argument("--seed", type=int, default=None, help="RNG seed")
    ap.add_argument("--dsn", default=os.environ.get("OMS_DSN", DEFAULT_DSN))
    ap.add_argument("--gateway-url", default=os.environ.get("GATEWAY_URL", "http://localhost:8000"))
    ap.add_argument("--dry-run", action="store_true", help="In ra stdout thay vì ghi Postgres / gọi gateway")
    args = ap.parse_args()

    rnd = random.Random(args.seed)
    print("Building catalog / indexes …")
    refs = Refs(rnd)
    if args.dry_run:
        oms, partner = StdoutOmsChannel(), StdoutPartnerChannel()
    else:
        oms, partner = OmsChannel(args.dsn), PartnerChannel(args.gateway_url, args.time_scale)

    print(f"Generating: rate={args.rate} ship/s, scale={args.time_scale}x, "
          f"update={args.update_pct:.0%}, cancel={args.cancel_pct:.0%}, partner={args.partner_share:.0%}, "
          f"legacy={args.legacy_pct:.0%}, duration={args.duration or 'inf'}")
    run(oms, partner, refs, rnd, args.rate, args.duration, args.time_scale, args.update_pct, args.cancel_pct,
        args.partner_share, args.legacy_pct)


if __name__ == "__main__":
    main()
