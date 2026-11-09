from __future__ import annotations

import itertools
import json
from datetime import datetime

from simulation.pricing import shipment_id


class OmsChannel:
    """Đóng vai ứng dụng OMS: INSERT / UPDATE bảng `orders`."""

    def __init__(self, dsn: str):
        import psycopg
        self.conn = psycopg.connect(dsn, autocommit=True)

    def next_shipment_id(self, created_at: datetime) -> str:
        return shipment_id(created_at, self.conn.execute("SELECT nextval('shipment_seq')").fetchone()[0])

    def insert_order(self, order: dict) -> None:
        cols = list(order)
        self.conn.execute(f"INSERT INTO orders ({', '.join(cols)}) VALUES ({', '.join(['%s'] * len(cols))})",
                          [order[c] for c in cols])

    def update_order(self, sid: str, fields: dict) -> None:
        sets = ", ".join(f"{c} = %s" for c in fields)
        self.conn.execute(f"UPDATE orders SET {sets} WHERE shipment_id = %s", [*fields.values(), sid])

    def close(self) -> None:
        self.conn.close()


class PartnerChannel:
    """Đóng vai sàn TMĐT: POST đơn lên partner gateway."""

    def __init__(self, gateway_url: str, time_scale: float):
        import httpx
        self.client = httpx.Client(base_url=gateway_url, headers={"X-Sim-Time-Scale": str(time_scale)}, timeout=30)

    def post_order(self, partner: str, payload: dict) -> dict:
        return self.client.post(f"/v1/partners/{partner}/orders", json=payload).json()

    def close(self) -> None:
        self.client.close()


class StdoutPartnerChannel:
    """Dry-run: in payload thay vì gọi gateway."""

    def post_order(self, partner: str, payload: dict) -> dict:
        print(f"partner.{partner}\t{json.dumps(payload, ensure_ascii=False)}")
        return {"status": "ACCEPTED"}

    def close(self) -> None:
        pass


class StdoutOmsChannel:
    """Dry-run: in câu lệnh thay vì ghi Postgres; sequence giả lập bằng bộ đếm."""

    def __init__(self):
        self._seq = itertools.count(1)

    def next_shipment_id(self, created_at: datetime) -> str:
        return shipment_id(created_at, next(self._seq))

    def insert_order(self, order: dict) -> None:
        print(f"oms.INSERT\t{json.dumps(order, ensure_ascii=False, default=str)}")

    def update_order(self, sid: str, fields: dict) -> None:
        print(f"oms.UPDATE\t{sid}\t{json.dumps(fields, ensure_ascii=False, default=str)}")

    def close(self) -> None:
        pass
