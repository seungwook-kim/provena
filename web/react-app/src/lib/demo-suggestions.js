// 서버에 연결된 채팅(api 모드)의 첫 화면 추천 질문. 키 없는 데모 모드는 `data/demo_replay/`에 녹화한 질문만 답하고, 녹화에 없는 질문은 거절로 끝난다.
// 그래서 추천 질문은 녹화 질문 목록(`data/demo_replay/questions.txt`, README "키 없이 뜨는 데모 모드")에서 글자 그대로 가져온다.
// 키가 있는 서버에서도 실제 정책 질문이라 그대로 답이 나온다. 질문을 바꾸면 `questions.txt`와 같은 글자인지 `demo-suggestions.test.js`가 본다.
// 서버 없이 도는 로컬 미리보기(`/demo/chat`)는 `chat-preview.js`의 `PREVIEW_SUGGESTIONS`를 쓴다.
export const DEMO_SUGGESTIONS = [
  '제3자가 프로덕션 데이터에 접근하거나 영향을 줄 수 있다면 보안 검토가 필요한가요?',
  '클라우드 호스팅 업체와 약정 사용 할인(CUD) 계약은 누가 승인해?',
  '외부 SaaS를 도입하려고 합니다. 계약 금액이 5만 달러라면 업무 승인자와 재무 승인자는 누구인가요?',
]
