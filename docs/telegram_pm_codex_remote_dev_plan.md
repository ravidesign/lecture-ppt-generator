# Teach-On PM Telegram + Codex Remote Dev Plan

작성일: 2026-04-21

## 한 줄 요약

가능하다. 다만 현재 코드에서 바로 되는 것은 아니고, `Telegram PM chat` 과 `PM dispatcher` 를 새로 만들고, 코딩 작업은 `Codex cloud 우선`, `local Codex bridge 보조` 구조로 나누는 것이 가장 현실적이다.

## 먼저 짚고 갈 현실

현재 Teach-On의 `pm` 에이전트는 “하위 에이전트에 실제로 일을 배분하는 실행 관리자”가 아니다.

현재 상태:

- `core/agent_control.py` 의 `pm` 은 수동 호출 시 판단과 다음 액션을 제안하는 역할이다.
- 실제 하위 stage orchestration 은 `flows/full_pipeline.py` 에 고정 로직으로 들어 있다.
- 즉, 지금은 “PM과만 대화하면 PM이 내부 agent를 실제 호출한다”가 아직 구현되어 있지 않다.

따라서 이번 설계의 핵심은 `PM을 채팅 인터페이스`가 아니라 `실행 가능한 dispatcher` 로 승격하는 것이다.

## 목표

사용자는 Telegram에서 PM에게만 말한다.

PM은 입력을 해석해서 다음 중 하나를 수행한다.

1. 직접 답변
2. 내부 Teach-On agent에게 하위 작업 배정
3. Codex에게 코딩 작업 배정
4. 진행 상황 요약과 결과 회신
5. 피드백을 받아 다음 iteration 시작

결과적으로 “원격에서도 제품 개발을 굴리는 PM 채널”을 만드는 것이 목표다.

## 권장 아키텍처

### 레이어 1. Telegram PM Interface

새 역할:

- 사용자는 Telegram bot과만 대화
- bot은 일반 agent 목록을 노출하지 않음
- 모든 입력은 PM 전용 inbox로 들어감

권장 명령:

- `/start`
- `/help`
- `/pm <message>`
- `/status`
- `/work <message>`
- `/approve <task-id>`
- `/reject <task-id> <reason>`

실제 사용은 slash command 없이 자연어로도 가능하게 설계할 수 있다.

예시:

- `PM, 다음 주까지 텔레그램 webhook 구현 계획 세워줘`
- `PM, 이 repo에서 Telegram webhook MVP 실제로 개발 시작해`
- `PM, 현재 진행중인 작업 요약해줘`
- `PM, reviewer 말고 Codex에 바로 맡겨서 구현해`

### 레이어 2. PM Dispatcher

새 파일 권장:

- `core/pm_dispatcher.py`

역할:

- 사용자의 메시지를 PM intent로 분류
- 실제 실행 가능한 work item으로 변환
- 내부 agent 또는 Codex로 route
- 결과를 다시 PM 관점으로 재정리

PM dispatcher는 자유서술 응답만 만들면 안 되고, 반드시 구조화된 JSON을 내야 한다.

권장 출력 스키마:

```json
{
  "mode": "answer|delegate_internal|delegate_codex_cloud|delegate_codex_local|mixed|reject",
  "summary": "PM의 핵심 판단",
  "reasoning": "왜 이 route를 택했는지",
  "internal_tasks": [
    {
      "agent": "reviewer",
      "target_ref": "uid-or-job",
      "instruction": "문항 중복과 난이도 점검",
      "priority": "high"
    }
  ],
  "codex_task": {
    "task_type": "ask|code|review|refactor",
    "repo": "owner/repo",
    "branch": "main",
    "prompt": "Implement Telegram webhook MVP for Teach-On",
    "deliverable": "patch+summary+tests"
  },
  "reply_style": "brief|standard|detailed"
}
```

핵심은 `PM이 결정`하고, 실제 side-effect는 시스템이 실행하는 구조다.

## 내부 agent 위임 설계

내부 agent 위임은 현재 코드 재사용이 쉽다.

재사용 대상:

- `core/agent_control.create_agent_task()`
- `core/agent_control.run_agent_task_async()`
- `core/dashboard_service.dashboard_job_detail()`

다만 바뀌어야 하는 점:

- 사용자가 직접 `reviewer` 나 `layout` 을 고르는 대신 PM이 선택
- Telegram에서는 agent 목록을 숨기고 PM만 노출
- PM이 생성한 internal task의 parent를 추적

추가 필드 권장:

- `parent_task_id`
- `delegated_by = "pm"`
- `transport = "telegram"`
- `transport_chat_id`
- `transport_message_id`

## Codex 연동 방식 비교

여기서 중요한 건 `VS Code 안의 Codex를 직접 원격 조작` 하느냐, `Codex 작업을 원격에서 발주하고 VS Code에서 이어받느냐` 이다.

결론부터 말하면, 권장안은 두 번째다.

### 옵션 A. Codex Cloud 우선

권장도: 가장 높음

구조:

`Telegram -> Teach-On PM -> Codex Cloud Task -> VS Code IDE Extension or Web에서 검토/후속작업`

이 방식을 권장하는 이유:

- OpenAI 공식 문서 기준 Codex cloud는 백그라운드 병렬 작업에 맞다.
- cloud task는 다른 디바이스나 서비스에서도 트리거 가능하다고 안내된다.
- IDE extension에서 cloud task를 생성, 추적, 리뷰, 이어서 마무리할 수 있다.
- 즉 “텔레그램에서 PM이 Codex 작업 발주 -> 나중에 VS Code에서 이어받아 마무리” 흐름이 공식 제품 개념과 가장 잘 맞는다.

필요 조건:

- Codex 사용 가능한 ChatGPT 플랜
- GitHub 저장소 연결
- 가능하면 repo를 GitHub 기준으로 운영
- Codex cloud 환경 설정

장점:

- 원격성 가장 좋음
- 개인 노트북이 항상 켜져 있지 않아도 됨
- VS Code는 review/finish 도구로 자연스럽게 사용 가능

한계:

- 로컬 미커밋 변경사항을 바로 다루는 구조에는 덜 적합
- GitHub 중심 운영이 필요
- Teach-On backend에서 Codex cloud task를 어떻게 생성할지 연결 방식 설계가 필요

### 옵션 B. Local Codex Bridge

권장도: 보조안

구조:

`Telegram -> Teach-On PM -> Local bridge daemon on dev machine -> codex CLI / local workspace`

이 방식은 개발 머신에서 로컬 Codex를 실행하는 별도 bridge 프로세스를 두는 구조다.

예:

- Mac mini 또는 항상 켜진 개발용 맥
- bridge가 `127.0.0.1` 또는 VPN 내부에서만 수신
- Telegram PM이 여기로 signed request 전송
- bridge가 `codex` 명령 실행

장점:

- 현재 로컬 작업중인 repo를 직접 다루기 좋음
- 로컬 미커밋 상태와도 잘 맞음

한계:

- 공식 제품 차원에서 “IDE extension 원격 제어 API”가 문서화되어 있지 않다
- 사실상 bridge가 CLI를 감싸는 구조가 됨
- 보안 리스크가 크다
- 개발 머신이 항상 켜져 있어야 함

따라서 `VS Code extension을 직접 원격 제어` 하려 하지 말고, `local Codex CLI bridge` 로 보는 것이 맞다.

### 옵션 C. Hybrid

권장도: 실무적으로 가장 좋음

구조:

- 일반 제품 기획, 리뷰, 문서화: 내부 Teach-On agent
- 실제 코드 수정/테스트/PR: Codex
- 빠른 원격 발주: Codex cloud
- 로컬 워크트리 긴급 작업: local bridge

추천 기본값:

- `기본 = Codex cloud`
- `예외 = local bridge`

## VS Code와 연결하는 권장 방식

권장 방식은 `Telegram -> PM -> Codex cloud task 생성 -> VS Code IDE extension에서 이어받기` 다.

이유:

- OpenAI 공식 문서상 IDE extension은 cloud task를 만들고, 진행 상태를 보고, 완료된 작업을 리뷰할 수 있다.
- cloud와 local 환경 사이에서 작업을 이어갈 수 있다고 명시되어 있다.
- 즉 제품 개발 원격 운영이라는 목적에 가장 잘 맞는다.

권장 워크플로:

1. 내가 Telegram에서 PM에게 요청
2. PM이 필요하면 Codex cloud task 생성
3. Codex가 GitHub 기준으로 작업
4. 나는 외부에서 Telegram으로 진행 보고 받음
5. 나중에 VS Code에서 Codex extension으로 작업 열기
6. 마지막 수동 수정/테스트/merge 수행

## Teach-On 기준 추천 최종 설계

### 1. PM-only Telegram 모드

환경변수:

- `TELEGRAM_PM_ONLY_MODE=true`

동작:

- Telegram에서는 오직 PM 채널만 노출
- 일반 agent 명령은 막음
- 모든 입력은 PM dispatcher를 통과

### 2. PM 라우팅 정책

PM은 입력을 다음 4종으로 분기한다.

- `answer_directly`
- `delegate_internal`
- `delegate_codex`
- `mixed`

예시:

- 기획/우선순위/품질 피드백: PM 직접 답변 또는 internal delegate
- 실제 구현, 리팩터링, 테스트 추가: Codex delegate
- 기능 정의 후 바로 구현까지: mixed

### 3. Codex Adapter

새 파일 권장:

- `core/codex_bridge.py`

mode:

- `cloud_sdk`
- `local_cli`

권장 public interface:

```python
create_codex_task(...)
get_codex_task(...)
list_codex_tasks(...)
cancel_codex_task(...)
format_codex_result_for_pm(...)
```

### 4. PM Memory / Task Graph

새 저장소 권장:

- `outputs/dashboard/pm_threads.json`
- `outputs/dashboard/codex_tasks.json`

저장 목적:

- Telegram thread 와 PM conversation 연결
- PM task와 internal subtask 연결
- PM task와 Codex task 연결

권장 관계:

- `pm_thread_id`
- `pm_task_id`
- `subtask_ids`
- `codex_task_ids`
- `source_message_ids`
- `status`

## 제안 데이터 모델

### PM Task

```json
{
  "id": "pm_20260421_001",
  "transport": "telegram",
  "chat_id": "123456789",
  "source_message_id": "991",
  "user_request": "텔레그램 webhook MVP 실제 구현해",
  "route": "delegate_codex_cloud",
  "status": "queued",
  "summary": "Webhook MVP는 Codex cloud에 맡기고 결과를 VS Code에서 마무리하는 것이 적합",
  "subtasks": [],
  "codex_tasks": ["cx_abc123"],
  "created_at": "2026-04-21T03:00:00Z"
}
```

### Codex Task Mirror

```json
{
  "id": "cx_abc123",
  "pm_task_id": "pm_20260421_001",
  "mode": "cloud_sdk",
  "repo": "owner/pdf-to-ppt",
  "branch": "main",
  "prompt": "Implement Telegram webhook MVP for Teach-On",
  "status": "running",
  "result_summary": "",
  "artifacts": [],
  "created_at": "2026-04-21T03:01:00Z"
}
```

## 보안 설계

### Telegram

- `X-Telegram-Bot-Api-Secret-Token` 검증
- `TELEGRAM_ALLOWED_CHAT_IDS` allowlist
- private chat 우선
- admin level command는 group 차단

### PM Dispatcher

- PM이 system-level side effect를 직접 실행하지 않게 하기
- PM은 구조화된 action plan만 제안
- executor layer가 allowlist 기반으로 실행

### Codex Cloud

- GitHub repo 권한 최소화
- 인터넷 access allowlist 최소화
- setup script 검토
- secret 노출 금지

### Local Bridge

- 외부 공개 금지
- reverse proxy + token + IP allowlist + VPN 권장
- 실행 가능한 command allowlist
- workspace root 고정
- destructive command 차단

## 구현 우선순위

### Phase 1. 설계 현실화

- Telegram PM-only mode
- PM dispatcher
- Telegram transport
- PM thread 저장

### Phase 2. 내부 agent delegation

- PM -> reviewer/layout/content/manual task dispatch
- PM 진행 요약 회신

### Phase 3. Codex integration

우선순위:

1. `cloud-first adapter`
2. `local bridge` 는 선택 구현

### Phase 4. VS Code workflow polish

- Codex cloud task id를 Telegram에서 추적
- VS Code에서 같은 task 여는 운영 가이드
- 승인/반려/재시도 버튼

## 내가 추천하는 최종 선택

추천안:

- Telegram에서는 PM하고만 대화
- PM이 내부 agent와 Codex를 route
- Codex는 `cloud-first`
- VS Code는 `review / continuation / finishing` 용
- local Codex bridge는 나중에 필요할 때만 추가

이 방식이 좋은 이유:

- 제품적으로 가장 안정적
- 보안 리스크가 낮음
- 원격 작업성이 좋음
- OpenAI 공식 Codex 제품 방향과도 가장 잘 맞음

## 이번 설계에서 바로 이어서 구현할 대상

코드 기준 첫 구현 대상:

1. `core/telegram_service.py`
2. `core/pm_dispatcher.py`
3. `POST /telegram/webhook`
4. `outputs/dashboard/pm_threads.json`
5. Telegram PM-only command parser

Codex는 그 다음 단계로 붙인다.

## 참고 자료

OpenAI 공식:

- Codex cloud overview: https://platform.openai.com/docs/codex/overview
- Codex code generation guide: https://platform.openai.com/docs/guides/code-generation
- Codex upgrades and IDE extension: https://openai.com/index/introducing-upgrades-to-codex/
- Codex GA and SDK: https://openai.com/index/codex-now-generally-available/
- Docs MCP for Codex CLI/IDE: https://platform.openai.com/docs/docs-mcp

Telegram 공식:

- Bot API: https://core.telegram.org/bots/api
- Bots FAQ: https://core.telegram.org/bots/faq

이 문서는 2026-04-21 기준 위 공식 문서를 확인해 작성했다.
