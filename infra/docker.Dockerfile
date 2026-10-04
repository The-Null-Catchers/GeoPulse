FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PYTHONPATH=/app/apps/api:/app/apps:/app/packages
WORKDIR /app
COPY apps/api/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt && groupadd -r geopulse && useradd -r -g geopulse geopulse
COPY apps/api /app/apps/api
COPY apps/worker /app/apps/worker
COPY apps/simulator /app/apps/simulator
COPY packages /app/packages
USER geopulse
EXPOSE 8000
CMD ["uvicorn", "geopulse.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]
