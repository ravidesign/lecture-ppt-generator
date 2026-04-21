# Teach-On Telegram Agent Integration Plan

작성일: 2026-04-20

## 목표

Teach-On의 기존 멀티 에이전트와 저장된 산출물 흐름을 유지한 채, Telegram에서 다음 작업을 수행할 수 있게 만든다.

- 명령 실행
- 에이전트 작업 접수
- 결과 보고
- 피드백 전달
- 재수정 또는 개선 루프 시작
- 최종 PPT/DOCX 전달

핵심 원칙은 Telegram을 새로운 “운영 채널”로 추가하되, 에이전트 실행과 산출물 저장 로직은 기존 코드를 최대한 재사용하는 것이다.

## 현재 재사용 가능한 구조

이미 구현되어 있는 재사용 포인트:

- 수동 에이전트 작업 생성과 비동기 실행: `core/agent_control.py`
- 저장된 산출물 조회: `core/dashboard_service.py`
- 슬라이드 재생성/수정/시안 적용: `app.py`
- Slack 기반 운영 채널 패턴: `core/slack_service.py`, `app.py`

즉, Telegram은 새 실행 엔진이 아니라 기존 실행 엔진의 새 transport layer로 설계한다.

## 공식 Bot API 제약과 설계 반영

2026-04-20 기준 Telegram Bot API 공식 문서에서 확인한 주요 조건:

- 업데이트 수신 방식은 `getUpdates` 와 `setWebhook` 중 하나만 사용 가능
- 운영 환경에서는 webhook 사용이 적합
- webhook은 HTTPS 필요
- 지원 포트는 `443`, `80`, `88`, `8443`
- `secret_token`을 설정하면 webhook 요청 헤더 `X-Telegram-Bot-Api-Secret-Token` 으로 검증 가능
- `callback_data` 는 1-64 bytes 제한
- `sendMessage` 본문은 1-4096자
- `sendDocument` 는 기본 Bot API 서버 기준 파일 전송 최대 50 MB
- `getFile` 다운로드는 기본 Bot API 서버 기준 최대 20 MB
- 더 큰 파일 업로드/다운로드가 필요하면 Local Bot API Server 검토 가능

이 제약을 바탕으로 Teach-On Telegram MVP는 다음처럼 제한한다.

- 최초 구현은 webhook 기반
- 명령과 결과 회신 위주로 시작
- PDF 업로드 기반 생성 플로우는 2단계 이후에 붙인다
- callback button payload는 짧은 action token으로 설계한다

## 범위 정의

### 1단계 MVP 범위

- Telegram bot webhook 수신
- 텍스트 명령 처리
- 에이전트 작업 생성
- 에이전트 결과 회신
- 저장된 결과물 링크 공유
- PPT/DOCX 파일 전송
- 운영 상태 확인용 dashboard status API

### 2단계 범위

- inline keyboard 기반 액션 버튼
- feedback 이후 재수정 루프 연결
- variant 생성/적용
- 산출물 승인/반려 흐름

### 3단계 범위

- Telegram으로 PDF 업로드
- `getFile` 다운로드 후 기존 analyze/generate 파이프라인 연결
- 대화형 step-by-step 작업 생성

## 제안 아키텍처

### A. Transport Layer

새 파일:

- `core/telegram_service.py`

역할:

- Telegram Bot API 호출 래퍼
- webhook 검증
- activity 로깅
- `sendMessage`, `sendDocument`, `editMessageText`, `answerCallbackQuery` 지원

기존 `core/slack_service.py` 와 유사한 구조로 만든다.

### B. Command Router

새 파일 권장:

- `core/chat_ops.py`

역할:

- Slack와 Telegram이 공통으로 쓰는 운영 명령 파싱
- 채널별 차이는 transport context로만 처리

이 레이어로 옮길 후보:

- `jobs`
- `status <uid-or-job>`
- `share <uid>`
- `task <agent> <uid> <instruction>`
- `feedback <uid> <message>`

지금의 `_handle_slack_command()` 에 있는 로직을 메신저 공통 로직으로 승격한다.

### C. App Routes

추가 라우트:

- `POST /telegram/webhook`
- `GET /api/dashboard/telegram/status`
- `POST /api/dashboard/telegram/test-post`

선택 라우트:

- `POST /api/dashboard/telegram/set-webhook`
- `POST /api/dashboard/telegram/delete-webhook`

### D. Persistence

새 파일 권장:

- `outputs/dashboard/telegram_activity.json`
- `outputs/dashboard/telegram_threads.json`

용도:

- 최근 Telegram 이벤트 추적
- chat/message 와 uid 또는 task_id 간 매핑 저장
- callback button 처리 시 문맥 복원

## 환경변수 제안

필수:

- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_WEBHOOK_SECRET`
- `TELEGRAM_WEBHOOK_ENABLED`

권장:

- `PUBLIC_BASE_URL`
- `TELEGRAM_DEFAULT_CHAT_ID`
- `TELEGRAM_ALLOWED_CHAT_IDS`

권한 제어 원칙:

- `TELEGRAM_ALLOWED_CHAT_IDS` 가 비어 있지 않으면 명시된 chat id만 허용
- private chat 우선
- group 사용은 2단계 이후 권장

## Telegram 명령 세트

MVP 명령:

- `/start`
- `/help`
- `/jobs`
- `/status <uid-or-job>`
- `/share <uid>`
- `/task <agent> <uid> <instruction>`
- `/feedback <uid> <message>`

권장 agent 목록:

- `pm`
- `curriculum`
- `content`
- `fact_checker`
- `question`
- `reviewer`
- `layout`
- `formatter`

추가 권장 명령:

- `/artifacts <uid>`
- `/ppt <uid>`
- `/docx <uid> exam|answer|exam_a|exam_b`

## Callback Button 설계

Telegram의 `callback_data` 는 64 bytes 제한이 있으므로 JSON 전체를 넣지 않는다.

권장 포맷:

- `tg:share:<uid>`
- `tg:status:<uid>`
- `tg:ppt:<uid>`
- `tg:regen:<uid>`
- `tg:var:<uid>:<slide_index>`

복잡한 상태는 `telegram_threads.json` 또는 저장 payload에서 복원한다.

버튼 예시:

- 상태 새로고침
- PPT 받기
- 문제지 받기
- PM 검토 요청
- Reviewer 재검토 요청

버튼 클릭 시 반드시 `answerCallbackQuery` 를 호출한다.

## 메시지 흐름 설계

### 1. 상태 조회

1. 사용자가 `/status <uid>` 전송
2. bot이 `dashboard_job_detail()` 로 조회
3. 요약 텍스트 + inline keyboard 전송
4. 버튼으로 `PPT 받기`, `문제지 받기`, `PM 호출`

### 2. 에이전트 작업

1. 사용자가 `/task reviewer <uid> 문항 중복 검토해줘`
2. bot이 `create_agent_task()` 호출
3. `run_agent_task_async()` 실행
4. 완료 시 Telegram으로 결과 회신

### 3. 피드백 루프

1. 사용자가 `/feedback <uid> 12번 슬라이드가 과밀함`
2. 1차로는 PM task 생성
3. 2단계부터는 PM 결과를 바탕으로 기존 `slides/<uid>/update` 또는 variant 흐름에 연결

### 4. 파일 전달

1. 사용자가 `/ppt <uid>`
2. bot이 저장된 artifact path 확인
3. `sendDocument` 로 파일 전송
4. 실패 시 다운로드 링크 fallback

## 보안 설계

필수:

- `X-Telegram-Bot-Api-Secret-Token` 검증
- 허용 chat id 검증
- bot 자신이 보낸 메시지는 무시
- callback_query 도 같은 권한 규칙 적용

권장:

- Telegram webhook 엔드포인트 별도 rate limit bucket
- dashboard 인증과 별도로 chat 기반 권한 제어
- 민감한 관리자 액션은 private chat 에서만 허용

Telegram은 Slack처럼 서명 방식이 아니라 webhook secret header와 bot token 기반 구조이므로, Slack 검증 코드를 재사용하지 말고 별도 검증 함수를 둔다.

## Dashboard 반영

Slack 섹션과 동일한 패턴으로 Telegram 운영 패널을 추가한다.

표시 항목:

- bot token 설정 여부
- webhook secret 설정 여부
- webhook enabled 여부
- webhook URL
- 허용 chat id 수
- 최근 Telegram activity
- 테스트 메시지 전송 UI

## 구현 단계 제안

### Phase 1

- `core/telegram_service.py`
- `POST /telegram/webhook`
- `GET /api/dashboard/telegram/status`
- `POST /api/dashboard/telegram/test-post`
- `/start`, `/help`, `/jobs`, `/status`, `/task`, `/feedback`, `/share`

### Phase 2

- 공통 command router 추출
- inline keyboard
- `sendDocument`
- Telegram activity 저장
- callback action 처리

### Phase 3

- 재수정 루프
- variant 생성/적용 버튼
- artifact 직접 승인 플로우

### Phase 4

- PDF 업로드 수신
- `getFile` 기반 다운로드
- analyze/generate 전체 파이프라인 연결

## 구현 시 주의점

- Telegram transport는 새로 만들되, 비즈니스 로직은 기존 함수 재사용이 우선이다.
- Slack와 Telegram 로직을 `app.py` 안에 계속 복붙하면 유지보수가 급격히 나빠진다.
- 따라서 Telegram 구현 전에 command parsing 과 task dispatch 를 공통 함수로 분리하는 것이 장기적으로 가장 중요하다.
- 파일 전송은 가능하지만 Telegram 기본 Bot API의 다운로드 20 MB 제한 때문에 PDF 업로드 수신은 바로 1단계에 넣지 않는다.
- callback button 은 payload 길이 제한 때문에 반드시 short token 설계를 따라야 한다.

## 완료 기준

다음이 되면 Telegram MVP 완료로 본다.

- private chat 에서 `/help` 와 `/jobs` 가 동작
- `/task reviewer <uid> ...` 가 실제 agent task 를 생성하고 결과를 회신
- `/share <uid>` 가 preview/download 링크를 보냄
- `/ppt <uid>` 가 artifact 파일을 전송
- webhook secret 과 chat allowlist 가 동작
- dashboard 에서 Telegram 상태와 테스트 전송이 보임

## 참고 자료

공식 문서:

- Telegram Bot API: https://core.telegram.org/bots/api
- Telegram Webhooks Guide: https://core.telegram.org/bots/webhooks

이 설계는 위 공식 문서를 2026-04-20 기준으로 확인한 내용에 맞춰 작성했다.
