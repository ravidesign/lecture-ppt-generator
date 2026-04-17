# PDF → 강의 교안 PPT 생성기

Flask + Claude API 기반의 PDF 강의 교안 자동 생성 도구.
PDF를 업로드하면 Claude가 분석해 슬라이드 JSON을 만들고, python-pptx로 .pptx를 메모리에서 생성해 스트리밍 다운로드한다.

---

## 배포 정보

- **GitHub**: `ravidesign/lecture-ppt-generator` (main 브랜치 push → Render 자동 배포)
- **Render URL**: `https://lecture-ppt-generator.onrender.com`
- **로컬 실행**: `http://localhost:5050`

---

## 프로젝트 구조

```
pdf-to-ppt/
├── app.py                   # Flask 라우터 (모든 API 엔드포인트)
├── core/
│   ├── claude_analyzer.py   # PDF → Claude API → slides JSON
│   ├── pdf_parser.py        # 페이지 선택, 이미지 추출 (PyMuPDF + Pillow)
│   ├── ppt_generator.py     # slides JSON + design → .pptx (python-pptx)
│   ├── slide_quality.py     # 슬라이드 품질 검사 및 content_kind 추론
│   ├── slide_enricher.py    # PDF 이미지를 슬라이드에 매핑
│   └── history.py           # 생성 히스토리 저장/조회 (history.json)
├── templates/
│   ├── index.html           # 메인 UI (업로드 → 분석 → 생성 → 완료)
│   └── preview.html         # 슬라이드 뷰어 (썸네일 + 편집 패널)
├── uploads/                 # 로고, PDF 이미지 번들 (PDF 자체는 처리 후 즉시 삭제)
├── outputs/                 # {uid}_slides.json만 저장 (.pptx 파일 없음)
├── Procfile                 # Render/gunicorn 실행 설정
├── CODEX_SPEC.md            # 디자인 시스템 업그레이드 상세 스펙 (CODEX 전달용)
└── requirements.txt
```

---

## 실행

```bash
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # ANTHROPIC_API_KEY 입력
python app.py          # http://localhost:5050
```

**환경변수**: `ANTHROPIC_API_KEY` (필수), `FLASK_PORT` (기본 5050), `UPLOAD_DIR`, `OUTPUT_DIR`

**Render/Production 실행** (`Procfile`):
```
PYTHONUTF8=1 PYTHONIOENCODING=utf-8 LANG=C.UTF-8 LC_ALL=C.UTF-8 gunicorn app:app --workers 2 --timeout 120 --bind 0.0.0.0:$PORT
```

---

## 핵심 데이터 흐름

```
[1] POST /api/analyze
    PDF 파일 + 옵션 (slide_count, page_range, extra_prompt, enhance_scans)
    → pdf_parser.resolve_page_selection()   # 페이지 범위 해석 (숫자/텍스트 힌트)
    → pdf_parser.extract_pdf_images()       # PDF 내 이미지 추출 → uploads/assets_{uid}/
    → claude_analyzer.analyze_pdf()         # Claude API → slides JSON
    → slide_quality.review_slides()         # 품질 검사 + content_kind 추론
    → slide_enricher.attach_pdf_images()    # 이미지를 슬라이드에 매핑
    → 응답: { slides, outline, quality, assets, uid, page_plan, ocr_available }

[2] POST /api/generate
    { slides, design, assets, pdf_name, page_plan }
    → slide_quality.review_slides()         # 재검토
    → slide_enricher.attach_pdf_images()    # 이미지 재매핑
    → outputs/{uid}_slides.json 저장       # 미리보기 + 다운로드 payload
    → .pptx 파일은 디스크에 저장하지 않음 (Render ephemeral filesystem 대응)
    → 응답: { ok, preview_uid, slide_count, preset, download_name }

[3] GET /preview/<uid>
    → preview.html 렌더링 (Jinja uid 변수 전달)
    → 클라이언트가 GET /api/slides/<uid> 호출해서 payload 로드

[4] GET /api/slides/<uid>
    → outputs/{uid}_slides.json 반환

[5] POST /api/slides/<uid>/update
    → 슬라이드 수정 후 outputs/{uid}_slides.json 재저장
    → .pptx 파일은 생성하지 않음

[6] GET /download/<uid>
    → outputs/{uid}_slides.json 로드
    → generate_pptx_bytes() 로 메모리에서 .pptx 생성 (BytesIO)
    → 파일 저장 없이 스트리밍 다운로드
    → ?name=파일명.pptx 쿼리로 다운로드 파일명 지정 가능
```

> **중요**: `/download/<uid>`는 요청 시점에 PPT를 즉시 재생성한다. 디스크에 .pptx 파일이 없어도 동작하지만, `outputs/{uid}_slides.json`이 없으면 404.

---

## 슬라이드 JSON 스키마

Claude가 반환하고 시스템 전체에서 사용하는 공통 구조.

```json
[
  { "type": "title",   "title": "강의 제목", "subtitle": "부제목" },
  { "type": "agenda",  "title": "목차", "items": ["주제1", "주제2"] },
  {
    "type": "content",
    "title": "슬라이드 제목",
    "subtitle": "선택적 보조 제목",
    "layout": "classic|split|card|highlight|process|compare|auto",
    "source_pages": "12-14",
    "points": ["핵심 포인트1", "핵심 포인트2"],
    "notes": "발표자 노트",
    "content_kind": "explain|process|compare|case|data",
    "image_bundle_uid": "abc12345",
    "image_asset_name": "img_001.png",
    "image_page": 7,
    "compare_left_title": "핵심 A",
    "compare_right_title": "핵심 B",
    "compare_left_points": ["..."],
    "compare_right_points": ["..."],
    "diagram_steps": ["1단계", "2단계", "3단계"]
  },
  { "type": "summary", "title": "핵심 요약", "points": ["요약1", "요약2"] }
]
```

**content_kind** (slide_quality.py가 키워드 기반으로 자동 추론):
- `explain`: 일반 설명 (기본값)
- `process`: 단계/절차 흐름 → `diagram_steps` 필드 자동 생성
- `compare`: 두 관점 비교 → `compare_*` 필드 자동 생성
- `case`: 사례/예시
- `data`: 수치/지표 중심

**layout** (Claude가 제안, slide_quality가 content_kind 기반으로 보정):
`classic` | `split` | `card` | `highlight` | `process` | `compare` | `auto`

---

## Design Config 스키마

`/api/generate` 요청의 `design` 필드. 모든 시각 스타일을 담는 객체.

```json
{
  "preset": "corporate",
  "primary_color": null,
  "accent_color": null,
  "font_name": "Malgun Gothic",
  "company_name": "",
  "presenter_name": "",
  "logo_uid": null,
  "footer_text": "",
  "footer_enabled": true,
  "slide_number": true,
  "content_layout": "auto",
  "title_font_size": 32,
  "subtitle_font_size": 18,
  "body_font_size": 18
}
```

- `preset`: 8종 중 하나 — `corporate` | `startup` | `academic` | `creative` | `terra` | `mono` | `forest` | `pastel`
- `primary_color` / `accent_color`: hex 문자열(`"#4A90D9"`)로 override. `null`이면 preset 색상 사용
- `logo_uid`: `/api/upload-logo` 응답의 uid. `uploads/logo_{uid}.{ext}` 경로로 저장됨
- `content_layout`: content 슬라이드 레이아웃 전역 설정. `auto`면 슬라이드별 layout 필드 우선
- 하위 호환: `theme` 문자열만 전달 시 `_coerce_design()`이 design 객체로 자동 변환

---

## API 엔드포인트 목록

| 메서드 | 경로 | 설명 |
|--------|------|------|
| GET | `/` | 메인 페이지 |
| GET | `/preview/<uid>` | 슬라이드 뷰어 페이지 |
| POST | `/api/analyze` | PDF 분석 → slides JSON |
| POST | `/api/generate` | slides → {uid}_slides.json 저장, 응답에 preview_uid 반환 |
| GET | `/api/slides/<uid>` | outputs/{uid}_slides.json payload 반환 |
| POST | `/api/slides/<uid>/update` | 슬라이드 수정 후 JSON 재저장 |
| POST | `/api/review-slides` | 슬라이드 품질 검사만 수행 |
| GET | `/api/presets` | 디자인 프리셋 목록 반환 |
| GET | `/api/fonts` | 지원 폰트 목록 반환 |
| GET | `/api/capabilities` | 서버 기능 (`ocr_available` 등) |
| POST | `/api/upload-logo` | 로고 이미지 업로드 |
| GET | `/api/logo/<logo_uid>` | 로고 이미지 반환 |
| GET | `/api/pdf-asset/<bundle_uid>/<asset_name>` | PDF에서 추출한 이미지 반환 |
| GET | `/api/history` | 생성 히스토리 (history.json) |
| GET | `/download/<uid>` | .pptx 스트리밍 다운로드 (메모리에서 즉시 생성) |

> **변경 이력**: 구버전의 `/download/<filename>` 엔드포인트는 `/download/<uid>`로 교체됨.

---

## 모듈별 역할 상세

### app.py
- 시작 시 `sys.stdout/stderr`를 UTF-8로 강제 재설정 (Render Linux ASCII 기본값 대응)
- logging 핸들러도 UTF-8로 설정
- `UID_RE = re.compile(r"^[a-f0-9]{8}$")`: 모든 uid 파라미터 검증 (경로 탐색 공격 방지)
- `_resolve_media_assets(assets)`: asset 경로 존재 여부 확인 후 resolved_assets 반환 (파일 없으면 graceful skip)
- `_coerce_design(body)`: theme 문자열 → design 객체 변환 (하위 호환)
- 에러 핸들러: `except Exception as exc: traceback.print_exc()` → Render 로그에서 traceback 확인 가능

### core/claude_analyzer.py
- `analyze_pdf(pdf_path, slide_count, page_range, extra_prompt)` → slides list
- 100페이지 이하: 단일 Claude API 호출 (`claude-opus-4-5` 모델)
- 100페이지 초과: 청크별 요약(`CHUNK_SYSTEM_PROMPT`) → 종합(`FINAL_SYSTEM_PROMPT`) 2단계
- `_load_json(raw_text)`: JSON 파싱 시 앞뒤 설명 텍스트 자동 제거 후 파싱 (Claude가 JSON 외 텍스트를 추가하는 케이스 대응)
- 슬라이드 JSON에 `layout`, `source_pages` 필드를 Claude가 직접 채움

### core/pdf_parser.py
- `resolve_page_selection(pdf_path, page_hint, max_pages_per_chunk)` → page_plan dict
  - 숫자 범위("1-5, 8") → `parse_page_range()`
  - 텍스트 힌트("서론 부분") → `select_pages_by_text_hint()` (TF-IDF 유사 점수 계산)
  - 힌트 없음 → 전체 페이지
- `extract_pdf_images()` → PDF 내 이미지 추출, `uploads/assets_{uid}/` 저장
- `extract_pages_as_bytes()` → 특정 페이지만 포함한 PDF bytes 반환

### core/ppt_generator.py
- `_build_presentation(slides_data, design, media_assets)` → `Presentation` 객체 (공유 코어)
- `generate_pptx(slides_data, output_path, design, media_assets)` → 디스크 저장 (하위 호환용, 현재 미사용)
- `generate_pptx_bytes(slides_data, design, media_assets)` → `BytesIO` (스트리밍 다운로드용, 현재 사용)
- `_resolve_theme(design)` → PRESETS + brand override → Resolved Theme dict
- 슬라이드 타입별 렌더 함수: `_title_slide`, `_agenda_slide`, `_content_slide_*`, `_summary_slide`
- content_layout별 렌더 함수 (전부 구현 완료):
  - `_content_slide_classic`: 불릿 리스트 + 선택적 이미지
  - `_content_slide_split`: 좌측 컬러 패널 + 우측 내용
  - `_content_slide_card`: 카드 그리드 (3×2)
  - `_content_slide_highlight`: 첫 포인트 강조 박스
  - `_content_slide_process`: 단계 흐름도 (화살표 연결)
  - `_content_slide_compare`: 좌우 2분할 비교
- `PRESETS`: 8종 프리셋 — `colors`, `header_style`, `bullet_style`, `density`
  - `header_style`: `full` | `bottom_line` | `left_bar`
  - `bullet_style`: `circle` | `square` | `number` | `dash`
  - `density`: `compact` | `standard` | `spacious`
- `LEGACY_THEME_PRESET_MAP`: `navy` → `corporate`, `terra` → `terra`, etc.
- `SUPPORTED_FONTS`: 맑은 고딕, 나눔고딕, 나눔바른고딕, 나눔명조, 프리텐다드, 애플 SD 고딕

### core/slide_quality.py
- `review_slides(slides_data, selected_pages)` → `{ slides, outline, quality }` dict
  - `infer_content_kind()`: 키워드 기반 content_kind 자동 추론
  - `_kind_layout()`: content_kind에 맞게 layout 필드 보정
  - `_normalize_source_pages()`: source_pages 정규화
  - `_dedupe_points()`: 중복 포인트 제거 (최대 5개)
  - `_ensure_notes()`: 발표자 노트 없으면 제목+첫 포인트 기반 자동 생성
  - `_derive_process_payload()`: process 슬라이드에 `diagram_steps` 필드 생성
  - `_derive_compare_payload()`: compare 슬라이드에 `compare_*` 필드 생성
- `build_outline(slides)` → 슬라이드 목차 구조 반환
- `build_quality_summary(slides)` → 품질 경고 dict 반환

### core/slide_enricher.py
- `attach_pdf_images_to_slides(slides, assets)` → 이미지-슬라이드 매핑
- `source_pages` 기준으로 같은 페이지 이미지 우선 매칭 (distance 기반 스코어링)
- 이미 매핑된 이미지 재사용 방지 (`used_asset_keys` 추적)

### core/history.py
- `add_record(pdf_name, uid, slide_count, theme)` → history.json에 추가 (최대 50개)
  - `uid`: generate endpoint에서 생성된 preview_uid 저장 (다운로드 링크용)
- `get_history()` → 전체 히스토리 반환

---

## 파일 저장 구조

```
uploads/
├── logo_{uid}.{ext}             # 업로드된 로고 (영구 보관)
└── assets_{uid}/
    ├── img_001.png              # PDF에서 추출한 이미지들
    └── img_002.png

outputs/
└── {uid}_slides.json            # 미리보기 + 다운로드용 payload
                                 # .pptx 파일은 저장하지 않음 (메모리에서 즉시 생성)
```

> PDF 원본(`{uid}.pdf`)과 OCR 처리본(`{uid}_ocr.pdf`)은 분석 완료 후 `finally` 블록에서 즉시 삭제.

**`{uid}_slides.json` 저장 구조**:
```json
{
  "slides": [...],
  "outline": [...],
  "quality": { "warnings": [...], "content_count": 8, ... },
  "design": { "preset": "corporate", ... },
  "assets": [{ "bundle_uid": "abc12345", "asset_name": "img_001.png", "page": 3 }],
  "page_plan": { "mode": "all", "selected_pages": [...] },
  "pdf_name": "강의자료.pdf",
  "download_name": "강의자료_강의교안.pptx"
}
```

---

## 개발 원칙

- `ANTHROPIC_API_KEY`는 `.env`에서만 관리. 코드에 하드코딩 금지. `.env`는 커밋 금지.
- uid 검증은 반드시 `UID_RE = re.compile(r"^[a-f0-9]{8}$")`로. 경로 탐색 공격 방지.
- 파일 다운로드명은 `_sanitize_download_name()`으로 특수문자 제거 후 사용.
- PDF는 처리 완료 후 즉시 삭제 (finally 블록). 로고와 이미지 번들은 영구 보관.
- 슬라이드 JSON은 항상 `slide_quality.review_slides()`를 거친 후 ppt_generator에 전달.
- python-pptx 좌표계: Inches 단위. 슬라이드 크기 13.33 × 7.5 Inches (16:9).
- OCR 기능(ocrmypdf + tesseract)은 선택적 — `OCR_AVAILABLE`로 체크 후 사용. Render 서버는 미지원이므로 UI에서 OCR 섹션 자체를 숨김.
- **Linux/Render UTF-8 인코딩**: `PYTHONUTF8=1` + `app.py` 시작 시 `sys.stdout.reconfigure(utf-8)` 이중 설정. 서드파티 라이브러리(anthropic SDK 등)의 로그에 Unicode가 포함될 때 발생하는 `UnicodeEncodeError` 방지.
- **.pptx 디스크 저장 없음**: Render free tier는 ephemeral 파일시스템이라 재시작 시 파일이 사라짐. `generate_pptx_bytes()` → `BytesIO` 스트리밍으로 대응. 다운로드 요청마다 JSON에서 PPT를 즉시 재생성.

---

## Render 배포 주의사항

- **Free tier 제약**: 15분 비활성 시 슬립 (첫 요청 30~50초 지연). 재시작 시 `uploads/`, `outputs/` 내 파일 모두 소실.
- **영구 보관 필요 파일** (현재 미적용): 로고(`uploads/logo_*`), 슬라이드 JSON(`outputs/*_slides.json`). Render Disk(유료) 또는 S3 연동으로 해결 가능.
- **대용량 PDF 주의**: 100페이지 초과 시 청크 분석으로 Claude API 다중 호출. 분석 시간이 길어져 Render 요청 타임아웃(기본 30초) 가능성 있음. gunicorn timeout은 120초로 설정했으나 Render 자체 제한이 우선.
- **배포 방식**: GitHub main 브랜치 push → Render 자동 감지 → pip install + 재시작.

---

## 현재 완료된 기능

- [x] PDF 업로드 + 페이지 범위 지정 (숫자/텍스트 힌트)
- [x] Claude API 분석 (claude-opus-4-5, 100페이지 초과 시 청크 처리)
- [x] 슬라이드 JSON 생성 + 품질 검사
- [x] PDF 이미지 추출 + 슬라이드 매핑
- [x] 8종 디자인 프리셋 (백엔드 구현 완료)
- [x] 6종 content layout 렌더러 (classic/split/card/highlight/process/compare)
- [x] 브랜드 커스터마이저 (primary_color, accent_color, font, logo, company_name)
- [x] 슬라이드 미리보기 페이지 (`/preview/<uid>`)
- [x] .pptx 스트리밍 다운로드 (디스크 저장 없음)
- [x] 생성 히스토리 (`/api/history`)
- [x] Render 배포 (Procfile, gunicorn, UTF-8 인코딩 대응)

## 미완료 / 다음 작업

- [ ] **프론트엔드 UI 연동**: 8종 프리셋 선택 UI, 브랜드 커스터마이저 패널, 레이아웃 선택 UI (CODEX_SPEC.md 참고)
- [ ] **preview.html 편집 패널**: 슬라이드 내용 직접 편집 + `/api/slides/<uid>/update` 연동 완성
- [ ] **영구 스토리지**: 로고/슬라이드 JSON을 S3 또는 Render Disk에 저장 (재시작 후 복원)
- [ ] **대용량 PDF 진행 상황 표시**: Server-Sent Events로 분석 진행률 스트리밍
