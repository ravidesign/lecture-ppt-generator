# 📚 Lecture. — PDF to PPT 강의 교안 생성기

## 설치

```bash
cd ~/Documents/pdf-to-ppt
pip3 install -r requirements.txt
cp .env.example .env
# .env 파일 열어서 ANTHROPIC_API_KEY, 필요하면 FIGMA_ACCESS_TOKEN / Telegram 설정 입력
```

## 실행

```bash
python3 app.py
# → http://localhost:5050
```

## Figma 연결 점검

Figma PAT는 `.env`의 `FIGMA_ACCESS_TOKEN`으로 읽습니다.

```bash
python3 -m tools.figma_tool me
```

- `GET /v1/me`를 호출합니다.
- Figma 공식 문서 기준 이 호출에는 `current_user:read` scope가 필요합니다.

파일 접근이 필요한 경우:

```bash
python3 -m tools.figma_tool file 'https://www.figma.com/design/FILE_KEY/Example'
python3 -m tools.figma_tool file-meta FILE_KEY
python3 -m tools.figma_tool register-connector --test
```

- `file`: `GET /v1/files/:key`를 사용하며 `file_content:read` scope가 필요합니다.
- `file-meta`: `GET /v1/files/:key/meta`를 사용하며 `file_metadata:read` scope가 필요합니다.
- `register-connector --test`: 대시보드용 Figma 커넥터를 저장하고 `GET /v1/me`로 상태를 점검합니다.

## Telegram PM 연동

Telegram 운영 채널 설계와 PM/Codex 확장 설계 문서는 아래에 정리했습니다.

- `docs/telegram_agent_integration_plan.md`
- `docs/telegram_pm_codex_remote_dev_plan.md`

실행에 필요한 기본 환경변수 예시:

```env
PUBLIC_BASE_URL=https://example.com
TELEGRAM_BOT_TOKEN=1234567890:telegram-bot-token
TELEGRAM_WEBHOOK_SECRET=teachon_telegram_secret
TELEGRAM_DEFAULT_CHAT_ID=
TELEGRAM_ALLOWED_CHAT_IDS=
TELEGRAM_WEBHOOK_ENABLED=true
TELEGRAM_PM_ONLY_MODE=true
PM_DISPATCH_ENABLED=true
PM_CODEX_ENABLED=false
PM_CODEX_MODE=cloud_sdk
CODEX_BRIDGE_URL=http://127.0.0.1:8765
CODEX_REPO_SLUG=owner/pdf-to-ppt
```

동작 경로:

- webhook URL: `POST /telegram/webhook`
- dashboard 상태 확인: `GET /api/dashboard/telegram/status`
- dashboard 테스트 발송: `POST /api/dashboard/telegram/test-post`

지원 명령:

- `/start`, `/help`
- `/jobs`
- `/status <uid-or-job>`
- `/share <uid>`
- `/feedback <uid> <message>`
- `/pm <message>`
- `/work <message>`

`TELEGRAM_PM_ONLY_MODE=true` 이면 일반 메시지도 PM inbox로 바로 들어갑니다.
실제 Telegram webhook 등록은 BotFather로 만든 bot token 기준으로 Telegram Bot API의 `setWebhook` 호출이 필요합니다.

## 사용 흐름

1. PDF 업로드
2. 슬라이드 장수 (5~20장) + 테마 선택
3. "분석 시작" → Claude가 구조 설계 (30~60초)
4. 슬라이드 미리보기 확인
5. "PPT 생성하기" → 브라우저 다운로드 + `outputs/` 자동 저장

## 테마

| 이름 | 특징 |
|------|------|
| 네이비 클래식 | 차분한 네이비, 블루 포인트 |
| 따뜻한 테라코타 | 따뜻한 브라운 계열 |
| 모노 미니멀 | 흑백, 깔끔한 강의 |
| 포레스트 그린 | 자연 친화적 그린 |

## 파일 구조

```
pdf-to-ppt/
├── app.py                  # Flask 서버
├── core/
│   ├── claude_analyzer.py  # Claude API 분석
│   ├── ppt_generator.py    # PPTX 생성 (4가지 테마)
│   └── history.py          # 히스토리 관리
├── templates/
│   └── index.html          # 웹 UI (다크 에디토리얼)
├── outputs/                # 생성된 PPT 저장
├── history.json            # 생성 히스토리 (자동 생성)
└── .env                    # API 키
```
