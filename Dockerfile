# G2: 평가자가 `docker compose up` 한 줄로 띄울 수 있어야 합니다.
FROM python:3.12-slim

WORKDIR /app

COPY backend/requirements.txt backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt

# 검색 모델(기본 임베딩·리랭커)을 고정 판(커밋)으로 이미지에 넣고, 실행 중에는 내려받지 않는다(키 없는 데모·오프라인, G2).
# 판은 backend/rag/retrieve/embed.py·rerank.py 명부와 같아야 한다(tests/test_search.py가 대조). 다른 후보 모델은 넣지 않는다(모델당 0.5~2GB).
# 코드보다 먼저 받아 두어 코드만 바꾸면 이 층은 다시 받지 않는다. 빈 값(--build-arg SEARCH_EMBED_MODEL=)이면 받지 않는다.
ENV HF_HOME=/app/.hf HF_HUB_OFFLINE=1
ARG SEARCH_EMBED_MODEL=Snowflake/snowflake-arctic-embed-l-v2.0
ARG SEARCH_EMBED_REVISION=ac6544c8a46e00af67e330e85a9028c66b8cfd9a
ARG SEARCH_RERANK_MODEL=cross-encoder/mmarco-mMiniLMv2-L12-H384-v1
ARG SEARCH_RERANK_REVISION=1427fd652930e4ba29e8149678df786c240d8825
RUN HF_HUB_OFFLINE=0 python -c "import os; from huggingface_hub import snapshot_download as get; [get(m, revision=r, ignore_patterns=['onnx/*', '*.onnx*', 'openvino/*'])  for m, r in ((os.environ['SEARCH_EMBED_MODEL'], os.environ['SEARCH_EMBED_REVISION']),               (os.environ['SEARCH_RERANK_MODEL'], os.environ['SEARCH_RERANK_REVISION'])) if m]"

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
