-- db/manual/chunks_hnsw_voyage4.sql : chunks의 voyage-4 벡터에 HNSW 색인을 만드는 수동 실행 파일이다.
-- 자동으로 적용되지 않는다. compose의 db 초기화는 db/ 바로 아래 파일만 실행하고 하위 폴더는 건너뛰며, load_snapshot과 시험도 이 파일을 읽지 않는다.
-- 실행: psql "$DATABASE_URL" -f db/manual/chunks_hnsw_voyage4.sql
--
-- 실행 전: 수집과 적재를 멈춘다. 일반 CREATE INDEX는 끝날 때까지 chunks 쓰기를 막는다(읽기는 막지 않는다).
-- 연결: SET이 세션에 남아야 하므로 직접 접속이나 세션 모드 풀러에서 실행한다.
-- 코드: SEARCH_HNSW=1일 때만 backend/rag/retrieve/search.py가 이 색인을 쓰는 질의를 보낸다. 그 밖에는 색인이 있어도 전수 비교다.
-- 전체 재적재: 색인을 지우고 적재한 뒤 이 파일을 다시 실행한다. 색인이 있는 채로 적재하면 삽입마다 색인을 고쳐 느려진다.
-- 모델 변경: 이 색인은 voyage-4(1024차원) 행만 담는다. 모델이나 차원을 바꾸면 이 파일과 search.py의 HNSW_DIMS를 함께 바꾼다.
-- 되돌리기: DROP INDEX IF EXISTS chunks_emb_hnsw_half;
-- 재실행: 파일 전체를 다시 실행해도 안전하다. 같은 이름의 색인이 있으면 CREATE INDEX는 건너뛰고 ANALYZE만 다시 돈다. 이름만 보므로 색인 정의를 바꿀 때는 먼저 지운다.

SET statement_timeout = 0;
CREATE INDEX IF NOT EXISTS chunks_emb_hnsw_half
  ON chunks USING hnsw ((embedding::halfvec(1024)) halfvec_ip_ops)
  WITH (m = 16, ef_construction = 128) WHERE embedder = 'voyage-4';
ANALYZE chunks;
