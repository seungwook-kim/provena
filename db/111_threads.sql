-- 사용자별 대화(thread) 목록 (G4, SDD 4-4 /threads). 100번대 = 김승욱 파트. 101 users, 102 결정표·승인, 103 토큰 폐기, 110 쟁점표 다음 번호다.
-- 읽고 쓰는 곳: backend/api/threads.py 의 PostgresThreadStore. 모든 조회에 user_id 조건을 붙여 남의 대화는 보이지 않는다.
-- thread_id 는 화면이 보낸(또는 서버가 만든) 바깥 이름이다. 그래프와 체크포인트에는 "<user_id>:<thread_id>" 를 쓰므로 같은 t1 도 사용자마다 따로다.
-- 대화 내용 전체는 여기에 두지 않는다(LangGraph 체크포인트에 있다). last 는 마지막 답 {kind, answer, answer_id, as_of} 하나다.
-- 컨테이너를 처음 만들 때 실행되고, 여러 번 돌려도 된다. 이미 만든 볼륨에는 자동으로 적용되지 않는다(db/db.md).
CREATE TABLE IF NOT EXISTS threads (
    user_id     text NOT NULL,                   -- 로그인한 사용자 user_id (쿠키에서만 얻는다)
    thread_id   text NOT NULL,
    title       text NOT NULL DEFAULT '',        -- 첫 질문 앞 80자
    status      text NOT NULL DEFAULT 'idle' CHECK (status IN ('idle', 'running', 'pending_approval')),
    last        jsonb,                           -- 마지막 답. 아직 없으면 NULL
    created_at  timestamptz NOT NULL DEFAULT now(),
    updated_at  timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (user_id, thread_id)
);
CREATE INDEX IF NOT EXISTS threads_user_updated_idx ON threads (user_id, updated_at DESC);

-- 앱은 DATABASE_URL 의 소유자 권한으로 읽고 쓴다(201_search.sql 과 같은 방침: RLS 를 켜고 정책을 두지 않아 공개 API 키로는 못 보게 잠근다)
ALTER TABLE threads ENABLE ROW LEVEL SECURITY;
