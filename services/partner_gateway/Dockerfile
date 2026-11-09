# Build từ gốc repo vì gateway dùng lại simulation/pricing.py và dữ liệu reference/admin_units.
FROM python:3.12-slim

WORKDIR /app
COPY services/partner_gateway/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY simulation simulation
COPY reference reference
COPY services services

CMD ["uvicorn", "services.partner_gateway.app:app", "--host", "0.0.0.0", "--port", "8000"]
