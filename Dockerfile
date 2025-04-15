FROM python:3.10-slim-bookworm

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*
	
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY bot.py .

COPY ip_cam.txt .

RUN useradd -m appuser && chown -R appuser:appuser /app

USER appuser

CMD ["python", "bot.py"]
