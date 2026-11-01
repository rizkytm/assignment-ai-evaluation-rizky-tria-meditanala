FROM python:3.11-slim

WORKDIR /app

# Install dependencies di layer terpisah agar Docker layer caching optimal:
# requirements.txt jarang berubah, source code sering berubah.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy source code dan data (knowledge base + mock tickets)
COPY app/ app/
COPY data/ data/

EXPOSE 8000

# Host 0.0.0.0 agar port ter-ekspos dari container, bukan hanya loopback.
# API key TIDAK di-bake ke image — dipasok lewat --env-file .env saat runtime.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
