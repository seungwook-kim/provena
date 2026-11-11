// 실제 서버(키 없는 데모 포함)에 연결된 채팅 첫 화면의 추천 질문(K-20).
// data/demo_replay/questions.txt 의 질문과 글자가 같아야 한다: 키 없는 데모는 녹화에 있는 질문만 인용 답을 낸다.
// (vite 미리보기용 목업 질문은 chat-preview.js 의 PREVIEW_SUGGESTIONS 이고, 서버를 부르지 않는다.)
export const RECORDED_SUGGESTIONS = [
  'CVSS 9.0 이상 크리티컬 취약점은 얼마 안에 완화(mitigate)하고 얼마 안에 수정(remediate)해야 해?',
  '클라우드 호스팅 업체와 약정 사용 할인(CUD) 계약은 누가 승인해?',
  'EOC가 호출에 응답하지 않으면 어떻게 에스컬레이션돼? IMOC도 응답이 없으면?',
]
