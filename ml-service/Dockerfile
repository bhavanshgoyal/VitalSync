FROM python:3.12-slim

WORKDIR /app

# Dependencies first so the layer caches across source edits.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY vitalsync_ml ./vitalsync_ml
COPY artifacts ./artifacts

ENV VITALSYNC_ARTIFACTS=/app/artifacts \
    PYTHONUNBUFFERED=1

EXPOSE 8000

HEALTHCHECK --interval=15s --timeout=5s --start-period=20s --retries=5 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8000/health',timeout=4).status==200 else 1)"

CMD ["uvicorn", "vitalsync_ml.service:app", "--host", "0.0.0.0", "--port", "8000"]
