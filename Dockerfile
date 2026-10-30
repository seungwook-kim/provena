# G2: 평가자가 `docker compose up` 한 줄로 띄울 수 있어야 합니다.
FROM python:3.12-slim

WORKDIR /app

COPY backend/requirements.txt backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt

COPY backend/ ./backend/
COPY data/ ./data/
COPY web/ ./web/
COPY db/ ./db/

EXPOSE 8000
# Cloud Run 앞단이 넘겨주는 X-Forwarded-For로 실제 접속 IP를 읽는다(로그인 IP별 실패 제한).
# 맨 앞 값은 클라이언트가 꾸밀 수 있어 IP 제한은 보조이고, ID별 제한이 주된 방어다.
CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips=*"]
