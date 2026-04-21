# Teach-On

Teach-On은 PDF 강의 자료를 분석해서 슬라이드 JSON, PPTX, 시험지 DOCX까지 생성하는 Flask 기반 강의안 제작 앱이다.  
현재는 단순 PDF->PPT를 넘어서 다음 운영 레이어가 함께 들어가 있다.

- 웹 분석/생성/미리보기/수정 플로우
- 멀티 에이전트 기반 강의안/문항 파이프라인
- 운영용 대시보드와 수동 에이전트 작업
- Slack 운영 채널
- Figma REST 연동과 Figma 설계 문서
- PM 전용 Telegram 운영 채널 1차 구현

## 주소

- GitHub: `ravidesign/lecture-ppt-generator`
- Production: `https://lecture-ppt-generator.onrender.com`
- Local: `http://localhost:5050`

## 빠른 실행

```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python app.py
```

## 핵심 환경변수

필수:

- `ANTHROPIC_API_KEY`

자주 쓰는 선택값:

- `FLASK_PORT`
- `UPLOAD_DIR`
- `OUTPUT_DIR`
- `PUBLIC_BASE_URL`
- `FIGMA_ACCESS_TOKEN`

Telegram PM 연동:

- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_WEBHOOK_SECRET`
- `TELEGRAM_WEBHOOK_ENABLED`
- `TELEGRAM_DEFAULT_CHAT_ID`
- `TELEGRAM_ALLOWED_CHAT_IDS`
- `TELEGRAM_PM_ONLY_MODE`
- `PM_DISPATCH_ENABLED`
- `PM_CODEX_ENABLED`
- `PM_CODEX_MODE`
- `CODEX_BRIDGE_URL`
- `CODEX_REPO_SLUG`

대시보드/보안:

- `TEACHON_ADMIN_TOKEN`
- `TEACHON_ADMIN_USERNAME`
- `TEACHON_ADMIN_PASSWORD`
- `TEACHON_ADMIN_PASSWORD_HASH`
- `TEACHON_DASHBOARD_IP_ALLOWLIST`

## 현재 아키텍처 요약

### 1. 사용자 생성 플로우

- `POST /api/analyze/start`
  PDF 업로드 후 비동기 분석 작업 생성
- `GET /api/analyze/status/<job_id>`
  분석 상태 폴링
- `POST /api/generate`
  슬라이드/디자인 기준으로 최종 산출물 저장
- `GET /preview/<uid>`
  저장된 payload 기반 미리보기/편집
- `GET /download/<uid>`
  저장된 PPT 아티팩트 다운로드

### 2. 멀티 에이전트 파이프라인

전체 stage 순서는 [flows/full_pipeline.py](./flows/full_pipeline.py) 기준이다.

1. PM kickoff
2. curriculum
3. content + question 병렬 초안
4. fact_checker
5. reviewer
6. layout
7. PM final review
8. formatter trace 반영 후 export

관련 런타임:

- [agents/](./agents)
- [tasks/](./tasks)
- [crews/](./crews)
- [flows/](./flows)
- [core/agent_control.py](./core/agent_control.py)

### 3. 대시보드 / 운영 레이어

대시보드는 다음을 다룬다.

- 최근 작업/결과 overview
- 보안 상태
- connector 등록/테스트
- 수동 agent task 실행
- Slack 상태
- Telegram 상태

핵심 파일:

- [app.py](./app.py)
- [core/dashboard_service.py](./core/dashboard_service.py)
- [templates/dashboard.html](./templates/dashboard.html)

### 4. 저장 구조

현재는 산출물이 디스크에도 저장된다.

- `uploads/{uid}.pdf`
- `uploads/logo_{uid}.{ext}`
- `uploads/assets_{uid}/img_*.png`
- `outputs/{uid}_slides.json`
- `outputs/pptx/{uid}.pptx`
- `outputs/docx/{uid}_*.docx`
- `outputs/dashboard/connectors.json`
- `outputs/dashboard/agent_tasks.json`
- `outputs/dashboard/slack_activity.json`
- `outputs/dashboard/telegram_activity.json`
- `outputs/dashboard/telegram_threads.json`
- `outputs/dashboard/pm_threads.json`

## 주요 파일 맵

- [app.py](./app.py): Flask 라우터 전체, 산출물 저장/수정, dashboard API, Slack/Telegram webhook
- [config.py](./config.py): 디렉터리/환경변수/LLM 설정
- [core/claude_analyzer.py](./core/claude_analyzer.py): PDF 기반 슬라이드 초안 분석
- [core/pdf_parser.py](./core/pdf_parser.py): 페이지 선택, 이미지 추출, PDF 파싱 보조
- [core/ppt_generator.py](./core/ppt_generator.py): PPTX 생성
- [core/slide_quality.py](./core/slide_quality.py): 슬라이드 품질 보정
- [core/slide_enricher.py](./core/slide_enricher.py): PDF 이미지와 슬라이드 매핑
- [core/slide_variants.py](./core/slide_variants.py): 슬라이드 시안 생성
- [core/agent_control.py](./core/agent_control.py): 수동 agent task 생성/실행/비동기 완료 처리
- [core/slack_service.py](./core/slack_service.py): Slack transport layer
- [core/telegram_service.py](./core/telegram_service.py): Telegram transport layer
- [core/pm_dispatcher.py](./core/pm_dispatcher.py): Telegram PM command/router
- [core/figma_client.py](./core/figma_client.py): Figma REST client
- [tools/figma_tool.py](./tools/figma_tool.py): Figma CLI helper
- [skills/teachon-agent-system/](./skills/teachon-agent-system): Codex local skill source

## Figma 현재 상태

현재 붙어 있는 것은 Figma REST 읽기/연결 점검 레이어다.

구현됨:

- `.env`의 `FIGMA_ACCESS_TOKEN` 사용
- `GET /v1/me`
- `GET /v1/files/:key`
- `GET /v1/files/:key/meta`
- 대시보드 connector 등록용 helper
- dashboard connector auth type `x_figma_token_env`

핵심 파일:

- [core/figma_client.py](./core/figma_client.py)
- [tools/figma_tool.py](./tools/figma_tool.py)
- [core/dashboard_service.py](./core/dashboard_service.py)
- [templates/dashboard.html](./templates/dashboard.html)

관련 문서:

- [docs/teachon_design_inventory.md](./docs/teachon_design_inventory.md)
- [docs/teachon_screen_map.md](./docs/teachon_screen_map.md)
- [docs/figma_project_structure.md](./docs/figma_project_structure.md)
- [docs/figma_layer_naming_system.md](./docs/figma_layer_naming_system.md)
- [docs/figma_build_sequence.md](./docs/figma_build_sequence.md)

중요:

- 아직 Figma canvas write는 없음
- 지금 세션 기준 구현은 REST read + 운영 문서 + connector 등록까지
- Figma에 실제 프레임/레이어를 쓰려면 Plugin API 또는 Figma MCP write 경로가 다음 단계

## Codex Skill 현재 상태

Teach-On 전용 운영 문서를 local skill 형태로 정리해 두었다.

- skill root: [skills/teachon-agent-system/SKILL.md](./skills/teachon-agent-system/SKILL.md)
- agent reference:
  - [pm.md](./skills/teachon-agent-system/references/pm.md)
  - [curriculum.md](./skills/teachon-agent-system/references/curriculum.md)
  - [content.md](./skills/teachon-agent-system/references/content.md)
  - [fact_checker.md](./skills/teachon-agent-system/references/fact_checker.md)
  - [question.md](./skills/teachon-agent-system/references/question.md)
  - [reviewer.md](./skills/teachon-agent-system/references/reviewer.md)
  - [layout.md](./skills/teachon-agent-system/references/layout.md)
  - [formatter.md](./skills/teachon-agent-system/references/formatter.md)
  - [system-map.md](./skills/teachon-agent-system/references/system-map.md)

로컬 환경에서는 `~/.codex/skills/teachon-agent-system` 심볼릭 링크로 연결한 상태를 전제로 작업했다.

## 마지막 작업 상세 정리

이 섹션은 다음 세션에서 바로 이어받기 위한 handoff 메모다.

작성 시점 기준 마지막 큰 작업은 `PM 전용 Telegram 운영 채널 1차 구현`이다.

### 무엇을 구현했는가

Telegram에서 일반 agent 목록을 노출하지 않고, 사용자가 PM과만 대화하는 운영 경로를 추가했다.

구현된 항목:

- Telegram runtime env/config 추가
- Telegram webhook 수신 라우트 추가
- Telegram dashboard status/test-post API 추가
- Telegram activity/thread 저장 추가
- PM inbox 전용 command/router 추가
- Telegram에서 생성된 manual agent task 결과를 같은 chat으로 회신하는 경로 추가
- agent task payload에 Telegram transport 메타데이터 추가

### 추가된/핵심 파일

- [config.py](./config.py)
  - `TELEGRAM_*`, `PM_*`, `CODEX_*` 환경변수 추가
  - Telegram/PM dashboard 저장 파일 경로 추가

- [core/telegram_service.py](./core/telegram_service.py)
  - `verify_request()`
  - `telegram_status()`
  - `record_telegram_activity()`
  - `record_thread_context()`
  - `send_message()`
  - `send_document()`
  - `answer_callback_query()`
  - `extract_update_context()`

- [core/pm_dispatcher.py](./core/pm_dispatcher.py)
  - `/start`, `/help`, `/jobs`, `/status`, `/share`, `/feedback`, `/pm`, `/work`
  - `TELEGRAM_PM_ONLY_MODE=true` 면 일반 텍스트도 PM inbox로 전달
  - `PM_DISPATCH_ENABLED=true` 여야 PM task 실제 생성
  - PM thread 로그는 `outputs/dashboard/pm_threads.json`

- [core/agent_control.py](./core/agent_control.py)
  - `transport`
  - `transport_chat_id`
  - `transport_message_id`
  - `parent_task_id`
  - `delegated_by`
  필드 추가

- [app.py](./app.py)
  - `POST /telegram/webhook`
  - `GET /api/dashboard/telegram/status`
  - `POST /api/dashboard/telegram/test-post`
  - Telegram task 완료 시 `_post_agent_task_result_to_telegram()`
  - webhook 수신 후 background thread에서 PM dispatcher 실행

### 현재 Telegram 명령 세트

- `/start`
- `/help`
- `/jobs`
- `/status <uid-or-job>`
- `/share <uid>`
- `/feedback <uid> <message>`
- `/pm <message>`
- `/work <message>`

PM only mode가 켜져 있으면 일반 메시지도 `/pm`처럼 동작한다.

### 현재 동작 한계

이 부분이 중요하다.

지금의 `pm` 은 아직 “실제 하위 agent와 Codex를 자동 위임하는 실행형 PM”이 아니다.

현재 상태:

- Telegram -> PM dispatcher -> `pm` manual task 생성 은 동작
- PM task 결과를 Telegram으로 돌려주는 구조도 동작
- 하지만 PM이 내부적으로 reviewer/content/layout 등을 자동 분기해서 여러 task를 만드는 로직은 아직 없음
- `PM_CODEX_ENABLED`, `PM_CODEX_MODE`, `CODEX_BRIDGE_URL`, `CODEX_REPO_SLUG` 는 설계용 env이고 실제 Codex orchestration은 아직 구현 전

즉, 지금은 `PM 전용 Telegram inbox` 까지는 구현됐고, `실행형 PM dispatcher` 는 다음 단계다.

### 검증 상태

완료:

- `python3 -m compileall config.py core app.py`
- `python3 -m py_compile core/pm_dispatcher.py core/telegram_service.py core/agent_control.py config.py`
- `pm_dispatcher.handle_telegram_message()` 스모크 테스트
- `telegram_service.extract_update_context()` 스모크 테스트

제한:

- 이 셸 환경에서는 `PyMuPDF(fitz)` import가 빠져 있어서 `app.py` 를 실제 Flask test client로 import해 webhook 엔드투엔드 검증까지는 못 했다
- 즉 Telegram 관련 신설 코드의 문법/모듈 레벨 검증은 됐고, 앱 전체 런타임 검증은 로컬 실행 환경에서 다시 확인 필요

### 다음 세션에서 바로 할 일

우선순위 순서:

1. `.env` 실제 값 확인
   - `PUBLIC_BASE_URL`
   - `TELEGRAM_BOT_TOKEN`
   - `TELEGRAM_WEBHOOK_SECRET`
   - `TELEGRAM_WEBHOOK_ENABLED=true`
   - `PM_DISPATCH_ENABLED=true`

2. Telegram webhook 등록
   - endpoint: `POST /telegram/webhook`
   - secret header는 `X-Telegram-Bot-Api-Secret-Token`

3. dashboard에서 연결 상태 점검
   - `GET /api/dashboard/telegram/status`
   - `POST /api/dashboard/telegram/test-post`

4. 실제 private chat에서 `/help`, `/jobs`, `/pm ...` 테스트

5. 다음 구현
   - PM이 내부 agent를 자동 위임하는 JSON dispatcher
   - PM -> Codex cloud/local bridge 연동
   - Telegram inline keyboard
   - dashboard UI에 Telegram 섹션 노출
   - 필요하면 artifact 전송을 `sendDocument()` 기준으로 연결

## 관련 설계 문서

- [docs/telegram_agent_integration_plan.md](./docs/telegram_agent_integration_plan.md)
- [docs/telegram_pm_codex_remote_dev_plan.md](./docs/telegram_pm_codex_remote_dev_plan.md)
- [docs/admin_security_plan.md](./docs/admin_security_plan.md)

## 운영 메모

- Render 배포는 `main` push 기준 자동 배포
- gunicorn 설정은 [Procfile](./Procfile) 참고
- UTF-8 강제 설정은 서버/로그/응답 안정성을 위해 유지 중
- dashboard auth와 IP allowlist는 같이 고려해야 함
- 수동 agent task는 dashboard/Slack/Telegram 모두 [core/agent_control.py](./core/agent_control.py) 를 공통 사용

## 다시 시작할 때 빠르게 볼 파일

다음 세션에서 먼저 열어볼 추천 순서:

1. [CLAUDE.md](./CLAUDE.md)
2. [app.py](./app.py)
3. [config.py](./config.py)
4. [core/pm_dispatcher.py](./core/pm_dispatcher.py)
5. [core/telegram_service.py](./core/telegram_service.py)
6. [core/agent_control.py](./core/agent_control.py)
7. [docs/telegram_pm_codex_remote_dev_plan.md](./docs/telegram_pm_codex_remote_dev_plan.md)
