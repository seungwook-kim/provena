# G2: 평가자가 `docker compose up` 한 줄로 띄울 수 있어야 합니다.
FROM python:3.12-slim

WORKDIR /app

COPY backend/requirements.txt backend/requirements-local-models.txt backend/
RUN pip install --no-cache-dir -r backend/requirements.txt

# 비교용 로컬 모델(임베딩·리랭커)은 서비스 이미지에 넣지 않는다. 확정 조합(voyage-4 API·리랭커 없음)은 내려받을 모델이 없고,
# 키가 없으면 검색은 빈 결과(no_key)로 돈다(G2 키 없는 데모). 비교할 때만 --build-arg로 모델 이름을 준다. 예:
#   --build-arg SEARCH_EMBED_MODEL=Snowflake/snowflake-arctic-embed-l-v2.0 --build-arg SEARCH_RERANK_MODEL=cross-encoder/mmarco-mMiniLMv2-L12-H384-v1
# 그러면 requirements-local-models.txt(torch CPU판 등)를 설치하고 모델을 고정 판(커밋)으로 받는다. 실행 중에는 내려받지 않는다(HF_HUB_OFFLINE=1).
# 판은 backend/rag/retrieve/embed.py·rerank.py 명부와 같아야 한다(tests/test_search.py가 대조). 모델 이름이 둘 다 비면(기본) 이 단계는 아무것도 하지 않는다.
ENV HF_HOME=/app/.hf HF_HUB_OFFLINE=1
ARG SEARCH_EMBED_MODEL=
ARG SEARCH_EMBED_REVISION=ac6544c8a46e00af67e330e85a9028c66b8cfd9a
ARG SEARCH_RERANK_MODEL=
ARG SEARCH_RERANK_REVISION=1427fd652930e4ba29e8149678df786c240d8825
RUN [ -z "$SEARCH_EMBED_MODEL$SEARCH_RERANK_MODEL" ] || { pip install --no-cache-dir -r backend/requirements-local-models.txt \
    && HF_HUB_OFFLINE=0 python -c "import os; from huggingface_hub import snapshot_download as get; [get(m, revision=r, ignore_patterns=['onnx/*', '*.onnx*', 'openvino/*'] + (['pytorch_model.bin'] if m in ('intfloat/multilingual-e5-large', 'cross-encoder/mmarco-mMiniLMv2-L12-H384-v1') else []))  for m, r in ((os.environ['SEARCH_EMBED_MODEL'], os.environ['SEARCH_EMBED_REVISION']),               (os.environ['SEARCH_RERANK_MODEL'], os.environ['SEARCH_RERANK_REVISION'])) if m]"; }

COPY backend/ ./backend/
COPY data/ ./data/
# 원문 스냅샷은 압축 한 파일로 커밋한다. 이미지를 만들 때 풀고 수집 때 sha256과 같은지 확인한다(다르면 빌드 실패)
RUN python -m backend.rag.ingest.snapshot unpack
# 검색 색인도 압축 한 파일(data/index.tar.gz)로 커밋한다. 풀린 data/index/는 .dockerignore로 빼므로 이미지 안에서 풀고
# meta.json의 sha256과 같은지 확인한다(다르면 빌드 실패). compose의 loader는 ./data/index를 연결하므로 그 폴더가 비어 있으면 시작할 때 다시 푼다
RUN python -m backend.rag.ingest.snapshot unpack-index
COPY web/ ./web/
COPY db/ ./db/
# 런타임 Skill(SKILL.md). backend/services/skills.py가 /app/skills/<이름>/SKILL.md를 읽는다. 이미지에 없으면 USE_SKILLS가 켜진 정책 질문이 FileNotFoundError로 실패한다
COPY skills/ ./skills/
# MCP 도구(MCP_TOKEN이 있을 때만 /mcp/에 붙음, docs/specs/mcp.md)
COPY extras/ ./extras/

EXPOSE 8000
# --no-proxy-headers: X-Forwarded-For로 client IP를 바꾸지 않는다. --forwarded-allow-ips=*이면 uvicorn이 맨 앞 값
# (요청하는 쪽이 마음대로 적을 수 있음)을 IP로 써서 IP별 로그인 실패 제한을 피할 수 있다. 로그인 Spec(직접 peer IP만 씀)과 같게 둔다.
# Cloud Run에서 실제 접속 IP를 쓰려면 프록시가 붙인 값만 믿는 처리를 로그인 코드에 따로 둔다(docs/specs/login.md 후속 검증 사항)
CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-proxy-headers"]
