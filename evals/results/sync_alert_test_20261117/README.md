# 증분 수집 실패 알림 메일 발송 기록 (준비 실패 유도, 2026-11-17 09:34 KST)

증분 수집 감싸개 [scripts/ops/sync_task.ps1](../../../scripts/ops/sync_task.ps1)가 실행에 실패하면 실제로 실패 알림 메일을 보내는지 확인한 기록이다. 감싸개는 동기화 종료 코드가 0이 아니거나, 준비 단계가 실패하거나, 시간 초과(30분)가 나면 Gmail SMTP(smtp.gmail.com:587, STARTTLS, 앱 비밀번호 로그인)로 메일 한 통을 보낸다(`docs/specs/incremental.md` "실행 주체와 실패 알림" 행). 이번 시험은 이 중 준비 실패 경로를 운영 DB와 동기화에 닿기 전에 일으켜 실패 메일 한 통을 팀 알림 주소로 보냈다. 발송은 팀장 승인 아래 한 번만 했다.

## 실행 내용

| 항목 | 내용 |
|---|---|
| 실행 시각 | 2026-11-17 09:34:36 KST 시작, 09:34:41 KST 준비 실패, 09:34:46 KST 메일 발송 완료 |
| 실행한 스크립트 | 저장소 사본 `scripts/ops/sync_task.ps1`(저장소 커밋 `e53713d8`, 수정 없이 그대로 실행) |
| 실행 방식 | Windows PowerShell 5.1(`powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -File ... -Trigger manual -LogDir <시험 로그 폴더>`), 작업 스케줄러 작업과 같은 실행 파일 |
| 환경 변수 | `PROVENA_GCP_PROJECT`, `PROVENA_GCP_REGION`, `PROVENA_RUN_SERVICE`, `PROVENA_GMAIL_SECRET_NAME`, `PROVENA_SYNC_ALERT_TO`는 작업 스케줄러가 실행하는 원본(`<사용자 폴더>\provena_sync\sync_task.ps1`)과 작업 등록 인자에서 읽어 이 실행의 자식 프로세스에만 넣었다(값은 화면·파일에 쓰지 않음) |
| 실패 유도 | `PROVENA_DB_SECRET_NAME`과 `PROVENA_VOYAGE_SECRET_NAME`을 존재하지 않는 Secret Manager 이름(`provena-alert-test-nonexistent-db-20261117`, `provena-alert-test-nonexistent-voyage-20261117`)으로 지정했다 |
| 오류 종류 | `preparation(준비 실패, 동기화 전)` |
| 종료 코드 | 2(준비 실패) |
| 메일 발송 결과 | `실패 알림 보냄: 메일(<알림 주소>) mail sent` |
| 메일 제목 | `[provena] 증분 수집 정시 실행 실패 2026-11-17`(감싸개는 trigger와 관계없이 같은 제목을 쓴다. 본문 첫 줄에 `trigger=manual`이 적힌다) |

## 실패가 일어난 위치와 닿지 않은 것

감싸개는 로컬 도구 확인, `git rev-parse`, `gcloud auth list`, 운영 Cloud Run 설정 조회(`gcloud run services describe`, 읽기만 함) 다음에 `DATABASE_URL` 비밀값을 받는다. 이번 실행은 이 단계에서 `gcloud secrets versions access`가 `NOT_FOUND`로 끝나 예외가 났고, 감싸개는 그 자리에서 준비 실패로 처리한 뒤 실패 알림 메일을 보냈다.

- `DATABASE_URL`과 `VOYAGE_API_KEY`는 받지 않았다. 로그에 "비밀값 받음" 줄이 없다.
- 동기화(`python -m backend.rag.ingest.schedule --once`)는 부르지 않았다. 로그에 "실행: python", "파이썬 출력", "sync_runs 요약" 줄이 없다. 따라서 운영 DB 연결, 핸드북 원천 조회, 임베딩 호출, `sync_runs` 기록은 일어나지 않았다.
- `-Trigger manual`로 실행했으므로 동기화까지 갔더라도 정시 슬롯을 쓰지 않는다.
- 작업 스케줄러 작업 `provena-handbook-sync`와 그 원본 스크립트는 바꾸지 않았다. 로그는 운영 로그 폴더가 아닌 별도 시험 폴더(`-LogDir`)에 썼다.
- Secret Manager에서 받은 값은 Gmail 앱 비밀번호 하나이며, 메일을 보내는 자식 파이썬 프로세스의 환경에만 넣고 끝난 뒤 버렸다(감싸개 동작 그대로).

## 파일

| 파일 | 내용 |
|---|---|
| `task_log_redacted.txt` | 이번 실행의 감싸개 로그 전체(18줄). 감싸개가 비밀값과 계정 주소를 원래 가려서 쓰며(`[가림]`), 추가로 개인 경로·컴퓨터 이름·GCP 프로젝트 번호·Secret Manager 이름·알림 주소를 자리 표시(`<사용자 폴더>`, `<컴퓨터>`, `<프로젝트 번호>`, `<DB 비밀 이름>`, `<알림 주소>` 등)로 바꿨다. 실패 유도에 쓴 존재하지 않는 비밀 이름은 그대로 두었다 |

## 수신 확인

- 2026-11-17 09:34 KST에 보낸 실패 알림 메일(제목 `[provena] 증분 수집 정시 실행 실패 2026-11-17`, 종료 코드 2, 오류 종류 `preparation(준비 실패, 동기화 전)`)이 알림 받는 메일함에 도착한 것을 팀장이 확인했다(2026-11-17 09:38 KST). 메일 본문의 시각, 종료 코드, 오류 종류는 위 로그와 같다.
- 같은 날 09:39 KST에 정시 작업의 알림 받는 주소를 팀장 메일로 바꾸고, 시험 알림(`-TestAlert`, 동기화 부르지 않음) 1통을 보냈다(로그 `시험 알림 보냄: 메일(<알림 주소>) mail sent`).
