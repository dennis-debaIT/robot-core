FROM python:3.12-slim

# ffmpeg für RTSP→HLS Live-Transcoding (Ring-Kameras via go2rtc)
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg git openssh-client tzdata && rm -rf /var/lib/apt/lists/*

RUN git config --global --add safe.directory /app

WORKDIR /app

# requirements zuerst kopieren → pip-Layer bleibt im Cache solange requirements unverändert
COPY backend/requirements.txt /app/requirements.txt
COPY backend/requirements-dev.txt /app/requirements-dev.txt
RUN pip install --no-cache-dir -r /app/requirements.txt -r /app/requirements-dev.txt

# GIT_HASH nach pip install → ändert sich jeden Commit, invalidiert nur die COPY-Schritte darunter
ARG GIT_HASH=unknown
ENV GIT_HASH=$GIT_HASH

COPY backend/app /app/app
COPY backend/tests /app/tests
COPY frontend /app/frontend
COPY VERSION /app/VERSION

ENV PYTHONUNBUFFERED=1
ENV PYTHONIOENCODING=UTF-8
ENV LANG=C.UTF-8
ENV LC_ALL=C.UTF-8
ENV ROBOT_CORE_DB_PATH=/data/robot_core.db

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
