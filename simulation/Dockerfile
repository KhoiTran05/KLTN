# Build từ gốc repo vì bộ sinh cần dữ liệu reference/admin_units.
FROM python:3.12-slim

WORKDIR /app
COPY simulation/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY simulation simulation
COPY reference reference

CMD ["python", "-m", "simulation.event_generator"]
