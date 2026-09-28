FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt && useradd -u 10001 -r appuser && mkdir /data && chown appuser /data
COPY app.py .
COPY templates ./templates
USER appuser
EXPOSE 8080
CMD ["python", "app.py"]
