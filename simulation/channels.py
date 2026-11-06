from __future__ import annotations

import itertools
import json
from datetime import datetime

from pricing import shipment_id


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
