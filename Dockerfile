# G2: 평가자가 `docker compose up` 한 줄로 띄울 수 있어야 합니다.
FROM node:22-alpine AS web-build

WORKDIR /web
COPY web/react-app/package.json web/react-app/package-lock.json ./
RUN npm ci
COPY web/react-app/ ./
# compose(로컬 데모)만 true로 빌드해 `/demo/*` 정적 미리보기 화면을 연다(놓친 것 H-25). 이 값은 `/demo/` 주소에만 쓰인다(`DemoPages.jsx` 가드).
# Cloud Run 소스 배포(`gcloud run deploy --source .`)는 빌드 인자를 주지 않아 false 그대로라 운영에서는 계속 닫힌다
ARG VITE_ENABLE_LOCAL_DEMO=false
ENV VITE_ENABLE_LOCAL_DEMO=$VITE_ENABLE_LOCAL_DEMO
RUN npm run build

FROM python:3.12-slim

# 서버는 root가 아닌 사용자(app, uid 10001)로 돈다. 코드·패키지는 root 소유(읽기 전용)로 두고,
# 실행 중에 쓰는 곳(data/ 아래 색인 다시 풀기·녹화, HF 캐시, 홈의 ~/.cache)만 app 소유로 둔다
RUN groupadd --system --gid 10001 app \
    && useradd --system --uid 10001 --gid app --create-home --home-dir /home/app --shell /usr/sbin/nologin app
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
# 받은 모델(HF_HOME)은 같은 단계에서 app 소유로 바꾼다(층이 두 번 쌓이지 않게). 모델이 없으면 빈 폴더만 만든다
RUN ( [ -z "$SEARCH_EMBED_MODEL$SEARCH_RERANK_MODEL" ] || { pip install --no-cache-dir -r backend/requirements-local-models.txt \
    && HF_HUB_OFFLINE=0 python -c "import os; from huggingface_hub import snapshot_download as get; [get(m, revision=r, ignore_patterns=['onnx/*', '*.onnx*', 'openvino/*'] + (['pytorch_model.bin'] if m in ('intfloat/multilingual-e5-large', 'cross-encoder/mmarco-mMiniLMv2-L12-H384-v1') else []))  for m, r in ((os.environ['SEARCH_EMBED_MODEL'], os.environ['SEARCH_EMBED_REVISION']),               (os.environ['SEARCH_RERANK_MODEL'], os.environ['SEARCH_RERANK_REVISION'])) if m]"; } ) \
    && mkdir -p "$HF_HOME" && chown -R app:app "$HF_HOME"

COPY backend/ ./backend/
# data/는 app 소유로 복사하고 압축 풀기도 app으로 돌려, 풀린 파일(data/corpus, data/index)과 실행 중에 쓰는 임시 폴더
# (data/index.tmp, 녹화 data/demo_replay)가 모두 app 소유가 되게 한다(chown -R로 큰 층을 다시 쌓지 않는다)
COPY --chown=app:app data/ ./data/
USER app
# 원문 스냅샷은 압축 한 파일로 커밋한다. 이미지를 만들 때 풀고 수집 때 sha256과 같은지 확인한다(다르면 빌드 실패)
RUN python -m backend.rag.ingest.snapshot unpack
# 검색 색인도 압축 한 파일(data/index.tar.gz)로 커밋한다. 풀린 data/index/는 .dockerignore로 빼므로 이미지 안에서 풀고
# meta.json의 sha256과 같은지 확인한다(다르면 빌드 실패). compose의 loader는 ./data/index를 연결하므로 그 폴더가 비어 있으면 시작할 때 다시 푼다
RUN python -m backend.rag.ingest.snapshot unpack-index
USER root
COPY web/ ./web/
COPY --from=web-build /web/dist/ ./web/react-app/dist/
RUN cp web/react-app/dist/index.html web/index.html
RUN cp web/react-app/dist/index.html web/login.html
COPY db/ ./db/
# 런타임 Skill(SKILL.md). backend/services/skills.py가 /app/skills/<이름>/SKILL.md를 읽는다. 이미지에 없으면 USE_SKILLS가 켜진 정책 질문이 FileNotFoundError로 실패한다
COPY skills/ ./skills/
# MCP 도구(MCP_TOKEN이 있을 때만 /mcp/에 붙음, docs/specs/mcp.md)
COPY extras/ ./extras/
# 업무시스템 목업(mock_erp/): 서버가 실행하지 않는 클라이언트·웹훅 수신기 예제 코드와 설명(시연용으로 이미지에 함께 둔다)
COPY mock_erp/ ./mock_erp/

USER app
EXPOSE 8000
# --no-proxy-headers: X-Forwarded-For로 client IP를 바꾸지 않는다. --forwarded-allow-ips=*이면 uvicorn이 맨 앞 값
# (요청하는 쪽이 마음대로 적을 수 있음)을 IP로 써서 IP별 로그인 실패 제한을 피할 수 있다.
# 프록시 뒤(Cloud Run)의 실제 접속 IP는 로그인 코드가 TRUSTED_PROXY_HOPS로 X-Forwarded-For 오른쪽에서 N번째 값만 믿어 얻는다
# (backend/auth.py `_client_ip`, Cloud Run은 1). 기본값 0은 직접 peer IP만 쓴다
CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-proxy-headers"]
