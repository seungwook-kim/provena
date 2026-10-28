# worklog

매일 한 일: 날짜, 한 일 2~3줄, 막힌 것, 다음 할 일. 최신이 위.

## 2026-10-28 : 강경희
# 오늘 한일
- Docker Compose로 FastAPI 로컬 실행 및 `/health` 정상 응답 확인
- Google Cloud Run에 `provena-api` 첫 배포 완료
- 배포 주소에서 `/health` 응답 `{"status":"ok"}` 확인
# 막힌 점 및 해결
- Cloud Run 빌드 계정 권한 오류 해결
- 외부 접근 제한 설정 변경 후 정상 접속 확인
# 다음 할 일
- 로그인 기능 구현을 위한 Spec 작성
- `backend/auth.py` 인증 기능 설계 및 팀원과 연동 방식 확인