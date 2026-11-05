-- 검색 파트 표 (SDD 5장 docs·versions·chunks + 색인 장부·번역 장부, docs/specs/search.md). 200번대 = 검색·데이터(박진형).
-- 컨테이너를 처음 만들 때 실행되고, 적재(backend/rag/retrieve/load_snapshot.py)도 매번 다시 실행한다. 여러 번 돌려도 된다.
CREATE EXTENSION IF NOT EXISTS vector;

-- 페이지 (rule_seq = 페이지 경로 sha256 앞 8자리를 정수로, 32비트를 넘어 BIGINT)
CREATE TABLE IF NOT EXISTS docs (
    rule_seq   bigint PRIMARY KEY,
    org        text NOT NULL,
    title      text NOT NULL,
    fmt        text NOT NULL DEFAULT 'md',
    source_url text NOT NULL,              -- 페이지 주소 (청크 주소의 #L… 를 뗀 것)
    fetched_at date NOT NULL
);

-- 판. version_id는 커밋 앞 12자라 여러 페이지가 같은 값을 쓴다 → 열쇠는 (rule_seq, version_id).
-- 유효 구간 [valid_from, valid_to): valid_from = 판 날짜, valid_to = 같은 페이지 다음 판 날짜, 현재 판은 비움.
CREATE TABLE IF NOT EXISTS versions (
    rule_seq            bigint NOT NULL REFERENCES docs (rule_seq),
    version_id          text NOT NULL,
    version_date        date NOT NULL,
    version_date_before boolean NOT NULL DEFAULT false,   -- "YYYY-MM-DD 이전" 판 (I-001)
    valid_from          date NOT NULL,
    valid_to            date,
    file_sha256         text,
    PRIMARY KEY (rule_seq, version_id),
    CHECK (valid_to IS NULL OR valid_to >= valid_from)
);
-- 한 페이지에 현재 판은 하나뿐 (옛 판을 닫지 않고 새 판을 넣으면 DB가 거부한다)
CREATE UNIQUE INDEX IF NOT EXISTS versions_one_current ON versions (rule_seq) WHERE valid_to IS NULL;

-- 청크. chunk_id = sha(rule_seq:seq:본문) 이라 개정판에서 안 바뀐 섹션은 옛 판과 id가 같다 → 열쇠는 (chunk_id, version_id).
-- embedding은 차원 없는 vector (모델마다 1024·2048). 한 번에 한 모델 벡터만 둔다(embedder = 그 행의 벡터를 만든 모델).
-- HNSW 색인은 만들지 않는다: 필터를 걸면 결과가 조용히 줄어든다(rag3-12). 전수 비교.
CREATE TABLE IF NOT EXISTS chunks (
    chunk_id    text NOT NULL,
    version_id  text NOT NULL,
    rule_seq    bigint NOT NULL,
    seq         integer NOT NULL,
    ord         integer NOT NULL,                -- 스냅샷 chunks.jsonl 의 줄 순서. BM25 색인 순서를 1차 비교와 같게 둔다
    article     text,
    kind        text NOT NULL,
    text        text NOT NULL,
    source_url  text NOT NULL,
    text_sha256 text,
    line_start  integer,                         -- 원본 페이지 줄 범위(1부터, 끝 포함). 평가셋 `경로#L123` 정답용
    line_end    integer,
    acl         text[] NOT NULL DEFAULT '{}',   -- 문서 권한 그룹 (F-06, 지금은 비움)
    embedding   vector,
    embedder    text,
    PRIMARY KEY (chunk_id, version_id),
    FOREIGN KEY (rule_seq, version_id) REFERENCES versions (rule_seq, version_id)
);
-- 줄 범위 칸이 생기기 전에 만든 DB에도 칸을 더한다(CREATE TABLE IF NOT EXISTS는 있는 표를 바꾸지 않는다)
ALTER TABLE chunks ADD COLUMN IF NOT EXISTS line_start integer;
ALTER TABLE chunks ADD COLUMN IF NOT EXISTS line_end integer;
-- 이 청크 본문의 링크가 가리키는 코퍼스 안 다른 페이지(rule_seq). 링크 확장(L1x2)이 읽는다. 판이 아니라 페이지라서
-- 대상 페이지가 개정돼도 as_of에 맞는 판의 청크를 고른다. 자기 페이지·코퍼스 밖·비공개 주소는 넣지 않는다(links.py).
ALTER TABLE chunks ADD COLUMN IF NOT EXISTS link_targets bigint[] NOT NULL DEFAULT '{}';
CREATE INDEX IF NOT EXISTS chunks_page ON chunks (rule_seq, version_id);

-- 색인 장부 (한 줄 = 지금 적재된 모델). status가 ready일 때만 api가 뜬다.
CREATE TABLE IF NOT EXISTS index_meta (
    id             smallint PRIMARY KEY DEFAULT 1 CHECK (id = 1),
    embedder       text NOT NULL,
    revision       text,
    dim            integer NOT NULL,
    prefixes       jsonb NOT NULL DEFAULT '{}',
    max_seq_length integer,
    n_chunks       integer NOT NULL,
    chunks_sha256  text NOT NULL,
    vectors_sha256 text NOT NULL,
    status         text NOT NULL CHECK (status IN ('loading', 'ready')),
    generation     bigint NOT NULL DEFAULT 0,       -- 적재·증분 반영마다 +1 (api가 BM25를 다시 만들 때 본다)
    loaded_at      timestamptz NOT NULL DEFAULT now()
);
-- 링크 파일(data/index/links.jsonl) sha256. 같은 스냅샷이어도 링크를 아직 안 실었으면 다시 적재한다
ALTER TABLE index_meta ADD COLUMN IF NOT EXISTS links_sha256 text;

-- 번역 장부: 같은 질문·같은 모델이면 LLM을 다시 부르지 않는다 (Spec). model은 cost.normalize_model_id 로 맞춘 이름.
CREATE TABLE IF NOT EXISTS query_translations (
    query_sha256 text NOT NULL,
    model        text NOT NULL,
    keywords     text,
    sentence     text,
    created_at   timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (query_sha256, model)
);

-- Supabase는 public 표를 Data API로 내보내고 새 표에 anon 권한을 연다. RLS를 켜고 정책을 두지 않아 anon과 authenticated를 막는다.
-- 앱과 적재는 표 소유자로 접속하므로 RLS의 영향을 받지 않는다. 다시 실행해도 되고 로컬 DB에서도 같은 문장이 돈다.
ALTER TABLE docs ENABLE ROW LEVEL SECURITY;
ALTER TABLE versions ENABLE ROW LEVEL SECURITY;
ALTER TABLE chunks ENABLE ROW LEVEL SECURITY;
ALTER TABLE index_meta ENABLE ROW LEVEL SECURITY;
ALTER TABLE query_translations ENABLE ROW LEVEL SECURITY;
