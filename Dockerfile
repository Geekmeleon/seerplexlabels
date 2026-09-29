FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    && apt-get update \
    && apt-get install -y --no-install-recommends gosu \
    && rm -rf /var/lib/apt/lists/* \
    && useradd -u 10001 -r appuser \
    && mkdir -p /data
COPY app.py .
COPY templates ./templates
EXPOSE 8080
CMD ["sh", "-c", "chown -R appuser:appuser /data && exec gosu appuser python /app/app.py"]
