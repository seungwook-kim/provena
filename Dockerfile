# G2: 평가자가 `docker compose up` 한 줄로 띄울 수 있어야 합니다.
FROM python:3.12-slim

WORKDIR /app

COPY backend/requirements.txt backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt

COPY backend/ ./backend/
COPY data/ ./data/
# 원문 스냅샷은 압축 한 파일로 커밋한다. 이미지를 만들 때 풀고 수집 때 sha256과 같은지 확인한다(다르면 빌드 실패)
RUN python -m backend.rag.ingest.snapshot unpack
COPY web/ ./web/
COPY db/ ./db/

EXPOSE 8000
# --no-proxy-headers: X-Forwarded-For로 client IP를 바꾸지 않는다. --forwarded-allow-ips=*이면 uvicorn이 맨 앞 값
# (요청하는 쪽이 마음대로 적을 수 있음)을 IP로 써서 IP별 로그인 실패 제한을 피할 수 있다. 로그인 Spec(직접 peer IP만 씀)과 같게 둔다.
# Cloud Run에서 실제 접속 IP를 쓰려면 프록시가 붙인 값만 믿는 처리를 로그인 코드에 따로 둔다(docs/specs/login.md 후속 검증 사항)
CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-proxy-headers"]
