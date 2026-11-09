"""S2 Partner gateway: kiểm tra schema, báo giá, cấp mã, ghi Kafka (docs/data_samples.md §2).

Header chỉ dùng trong mô phỏng:
  X-Sim-Fault        STALE_PRICING_VERSION | MISSING_REMOTE_FEE | WRONG_INSURANCE: tiêm lỗi cước.
  X-Sim-Time-Scale   Hệ số nén TIME_SCALE của thời hạn giao (mặc định 1 = không nén).
"""
from __future__ import annotations

import json
import os
import re
import time
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from typing import Annotated, Literal

from fastapi import Body, FastAPI, Header
from fastapi.responses import JSONResponse
from pydantic import AfterValidator, AwareDatetime, BaseModel, Field, StringConstraints, ValidationError
from pydantic_core import PydanticCustomError

from simulation import pricing
from simulation.reference.address_lookup import AddressLookup
from simulation.reference.catalog import build_catalog

TZ = timezone(timedelta(hours=7))
TOPIC_RAW = "partner.orders.raw"
TOPIC_DLQ = "logistics.orders.dlq"
SCHEMA_VERSION = "v2.0"
REFS_TTL_SECONDS = 60


def _check_phone(v: str) -> str:
    if not re.fullmatch(r"(\+?84|0)[35789]\d{8}", re.sub(r"[\s.\-]", "", v)):
        raise PydanticCustomError("INVALID_PHONE", "Số điện thoại không hợp lệ")
    return v


Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
Phone = Annotated[Text, AfterValidator(_check_phone)]


class Order(BaseModel):
    """Các trường dùng chung sau khi đọc schema riêng của từng đối tác."""
    partner_id: str
    partner_schema: str
    partner_order_ref: str
    merchant_id: str
    created_at: datetime
    service_type_id: str
    receiver_province: str
    receiver_district: str | None
    receiver_ward: str | None
    weight_gram: int
    length_cm: int | None
    width_cm: int | None
    height_cm: int | None
    declared_value_vnd: int | None
    cod_amount_vnd: int


# ---- Shopee (§2.1)
class ShopeeShop(BaseModel):
    merchant_code: Text


class ShopeePickup(BaseModel):
    name: Text
    phone: Phone
    full_address: Text


class ShopeeRecipient(ShopeePickup):
    city: Text
    district: str | None = None
    ward: str | None = None


class ShopeeDimension(BaseModel):
    l: int = Field(gt=0)
    w: int = Field(gt=0)
    h: int = Field(gt=0)


class ShopeeParcel(BaseModel):
    weight_kg: float = Field(gt=0)
    dimension_cm: ShopeeDimension | None = None


class ShopeeOrder(BaseModel):
    order_sn: Text
    shop: ShopeeShop
    create_time: int
    service_code: Literal["SD", "EXP", "ND", "STD", "ECO"]
    pickup: ShopeePickup
    recipient: ShopeeRecipient
    parcel: ShopeeParcel
    cod_amount: int = Field(default=0, ge=0)
    item_value: int | None = Field(default=None, ge=0)
    fee_paid_by: Literal["buyer", "seller"]

    def to_order(self) -> Order:
        d = self.parcel.dimension_cm
        return Order(
            partner_id="SHOPEE", partner_schema="shopee.v1", partner_order_ref=self.order_sn,
            merchant_id=self.shop.merchant_code, created_at=datetime.fromtimestamp(self.create_time, TZ),
            service_type_id={"SD": "SAMEDAY", "EXP": "EXPRESS", "ND": "NEXTDAY", "STD": "STANDARD",
                             "ECO": "ECONOMY"}[self.service_code],
            receiver_province=self.recipient.city, receiver_district=self.recipient.district,
            receiver_ward=self.recipient.ward, weight_gram=round(self.parcel.weight_kg * 1000),
            length_cm=d.l if d else None, width_cm=d.w if d else None, height_cm=d.h if d else None,
            declared_value_vnd=self.item_value, cod_amount_vnd=self.cod_amount)


# ---- TikTok Shop (§2.2)
class TiktokMoney(BaseModel):
    amount: int = Field(ge=0)
    currency: Literal["VND"]


class TiktokAddress(BaseModel):
    line1: Text
    ward: str | None = None
    district: str | None = None
    province: Text


class TiktokParty(BaseModel):
    contactName: Text
    contactPhone: Phone
    address: TiktokAddress


class TiktokPackage(BaseModel):
    weightGram: int = Field(gt=0)
    lengthCm: int | None = Field(default=None, gt=0)
    widthCm: int | None = Field(default=None, gt=0)
    heightCm: int | None = Field(default=None, gt=0)


class TiktokOrder(BaseModel):
    orderId: Text
    sellerId: Text
    createdAt: AwareDatetime
    shippingService: Literal["SAMEDAY", "EXPRESS", "NEXTDAY", "STANDARD", "ECONOMY"]
    sender: TiktokParty
    receiver: TiktokParty
    package: TiktokPackage
    codAmount: TiktokMoney | None = None
    declaredValue: TiktokMoney | None = None
    payer: Literal["SELLER", "BUYER"]

    def to_order(self) -> Order:
        addr = self.receiver.address
        return Order(
            partner_id="TIKTOK_SHOP", partner_schema="tiktok.v1", partner_order_ref=self.orderId,
            merchant_id=self.sellerId, created_at=self.createdAt.astimezone(TZ),
            service_type_id=self.shippingService, receiver_province=addr.province,
            receiver_district=addr.district, receiver_ward=addr.ward, weight_gram=self.package.weightGram,
            length_cm=self.package.lengthCm, width_cm=self.package.widthCm, height_cm=self.package.heightCm,
            declared_value_vnd=self.declaredValue.amount if self.declaredValue else None,
            cod_amount_vnd=self.codAmount.amount if self.codAmount else 0)


_MODELS = {"shopee": ShopeeOrder, "tiktok": TiktokOrder}
_MERCHANT_FIELD = {"shopee": "shop.merchant_code", "tiktok": "sellerId"}
_PROVINCE_FIELD = {"shopee": "recipient.city", "tiktok": "receiver.address.province"}


class Backend:
    """Postgres OMS (bảng giá, merchant, sequence mã vận đơn) và Kafka."""

    def __init__(self, dsn: str, bootstrap: str):
        import psycopg
        from kafka import KafkaProducer
        self.conn = psycopg.connect(dsn, autocommit=True, row_factory=psycopg.rows.dict_row)
        self.producer = KafkaProducer(
            bootstrap_servers=bootstrap,
            value_serializer=lambda v: json.dumps(v, ensure_ascii=False).encode("utf-8"),
            key_serializer=lambda k: k.encode(), acks=1, retries=3)

    def load_refs(self) -> dict:
        query = lambda sql: self.conn.execute(sql).fetchall()
        return {
            "rules": query("SELECT * FROM pricing_rules"),
            "sla": {(s["service_type_id"], s["zone_type"]): s for s in query("SELECT * FROM sla_config")},
            "merchants": {m["merchant_id"]: m for m in query("SELECT * FROM merchants WHERE status = 'ACTIVE'")},
        }

    def next_seq(self) -> int:
        return self.conn.execute("SELECT nextval('shipment_seq') AS seq").fetchone()["seq"]

    def send(self, topic: str, key: str, value: dict) -> None:
        self.producer.send(topic, key=key, value=value).get(timeout=10)


@asynccontextmanager
async def lifespan(_: FastAPI):
    global backend
    backend = Backend(os.environ["OMS_DSN"], os.environ["KAFKA_BOOTSTRAP"])
    yield


app = FastAPI(title="Partner gateway", lifespan=lifespan)
backend: Backend | None = None
lookup = AddressLookup()
_catalog = build_catalog()
_wards = {w["ward_id"]: w for w in _catalog["dim_ward"]}
_provinces = {p["province_id"]: p for p in _catalog["dim_province"]}
_refs_cache: tuple[float, dict] = (0.0, {})


def _refs() -> dict:
    """Bảng giá, SLA, merchant đọc từ OMS, làm mới sau mỗi REFS_TTL_SECONDS."""
    global _refs_cache
    if time.time() - _refs_cache[0] > REFS_TTL_SECONDS:
        _refs_cache = (time.time(), backend.load_refs())
    return _refs_cache[1]


def _receiver_ward(province_id: str, ward_id: str | None) -> dict:
    """Dòng dim_ward của xã nhận; không tra được xã thì lùi về thông tin cấp tỉnh để báo giá."""
    if ward_id:
        return _wards[ward_id]
    return {"province_id": province_id, "ward_type": None, "is_remote": _provinces[province_id]["is_remote"]}


def _reject(partner: str, request_id: str, errors: list[dict], body: dict) -> JSONResponse:
    backend.send(TOPIC_DLQ, request_id, {
        "dlq_id": str(uuid.uuid4()), "failed_at": datetime.now(TZ).isoformat(),
        "source_channel": "PARTNER_API", "source_ref": f"{partner}:{request_id}", "stage": "GATEWAY",
        "errors": [f"{e['field']}:{e['code']}" for e in errors], "raw": body,
    })
    return JSONResponse(status_code=400, content={"status": "REJECTED", "errors": errors, "request_id": request_id})


def _error_code(e: dict) -> str:
    if e["type"] in ("missing", "string_too_short") or e.get("input") is None:
        return "REQUIRED"
    return "INVALID_PHONE" if e["type"] == "INVALID_PHONE" else "INVALID"


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/v1/partners/{partner}/orders")
def create_order(
    partner: Literal["shopee", "tiktok"],
    body: dict = Body(...),
    x_sim_fault: Literal["STALE_PRICING_VERSION", "MISSING_REMOTE_FEE", "WRONG_INSURANCE"] | None = Header(default=None),
    x_sim_time_scale: float = Header(default=1.0, gt=0),
):
    request_id = f"req_{uuid.uuid4().hex[:8]}"
    try:
        order = _MODELS[partner].model_validate(body).to_order()
    except ValidationError as exc:
        errors = [{"field": ".".join(str(p) for p in e["loc"]), "code": _error_code(e)} for e in exc.errors()]
        return _reject(partner, request_id, errors, body)

    refs = _refs()
    merchant = refs["merchants"].get(order.merchant_id)
    province_id, ward_id = lookup.resolve(order.receiver_province, order.receiver_district, order.receiver_ward)
    errors = []
    if merchant is None:
        errors.append({"field": _MERCHANT_FIELD[partner], "code": "UNKNOWN_MERCHANT"})
    if province_id is None:
        errors.append({"field": _PROVINCE_FIELD[partner], "code": "UNKNOWN_PROVINCE"})
    if errors:
        return _reject(partner, request_id, errors, body)

    # Xã gửi lấy theo hồ sơ merchant; xã nhận tra từ địa chỉ trong request
    zone = pricing.zone_type(_wards[merchant["pickup_ward_id"]], _receiver_ward(province_id, ward_id))
    args = (order.weight_gram, order.length_cm, order.width_cm, order.height_cm,
            order.declared_value_vnd, order.cod_amount_vnd, merchant["discount_pct"])
    if x_sim_fault:
        quote = pricing.faulty_quote(x_sim_fault, refs["rules"], order.service_type_id, zone, order.created_at, *args)
    else:
        rule = pricing.find_rule(refs["rules"], order.service_type_id, zone, order.created_at)
        quote = pricing.quote(rule, zone, *args)
    promised = pricing.promised_delivery_at(
        order.created_at, refs["sla"][(order.service_type_id, zone)], x_sim_time_scale).isoformat()
    shipment_id = pricing.shipment_id(order.created_at, backend.next_seq())

    backend.send(TOPIC_RAW, shipment_id, {
        "event_id": str(uuid.uuid4()), "event_type": "partner_order_received",
        "event_time": order.created_at.isoformat(), "processing_time": datetime.now(TZ).isoformat(),
        "schema_version": SCHEMA_VERSION, "shipment_id": shipment_id, "source_system": "PARTNER_API",
        "partner_id": order.partner_id, "partner_schema": order.partner_schema,
        "partner_order_ref": order.partner_order_ref, "merchant_id": order.merchant_id,
        "request_id": request_id, "quote": quote, "promised_delivery_at": promised, "payload": body,
    })
    return {"tracking_number": shipment_id, "status": "ACCEPTED", "quote": quote, "promised_delivery_at": promised}
