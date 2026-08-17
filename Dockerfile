FROM python:3.11-slim

# Force Asia/Shanghai so datetime.now() matches the host's wall clock
# (shared with video-studio and all other skills on this VM).
ENV PYTHONUNBUFFERED=1 \
    TZ=Asia/Shanghai

WORKDIR /app

# curl for HEALTHCHECK. We don't need ffmpeg inside this container —
# WeChat API calls (token + image upload) are HTTP only.
# tesseract-ocr backs image_gen.detect_text: pseudo-text in AI artwork is
# rejected locally so no cloud OCR account or quota is needed.
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl ca-certificates \
        tesseract-ocr tesseract-ocr-eng \
    && rm -rf /var/lib/apt/lists/*

# Install Python deps first (better Docker layer cache).
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the versioned application. Customer profiles under clients/ are local
# data and are mounted by Docker Compose when present.
COPY webapp/ ./webapp/
COPY toolkit/ ./toolkit/
COPY scripts/ ./scripts/
COPY references/ ./references/
COPY config.yaml ./
COPY VERSION ./

RUN mkdir -p /app/logs

EXPOSE 9997

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -fsS -m 3 http://127.0.0.1:9997/api/health || exit 1

CMD ["gunicorn", "-c", "webapp/gunicorn.conf.py", "webapp.app:app"]
