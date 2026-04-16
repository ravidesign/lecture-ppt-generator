# PDF → 강의 교안 PPT 생성기

Flask + Claude API 기반의 PDF 강의 교안 자동 생성 도구.
PDF를 업로드하면 Claude가 분석해 슬라이드 JSON을 만들고, python-pptx로 .pptx 파일을 생성한다.

---

## 프로젝트 구조

```
pdf-to-ppt/
├── app.py                   # Flask 라우터 (API 엔드포인트 전부)
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
├── uploads/                 # PDF 임시 저장, 로고, PDF 이미지 번들
├── outputs/                 # 생성된 .pptx + {uid}_slides.json
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

환경변수: `ANTHROPIC_API_KEY`, `FLASK_PORT` (기본 5050), `UPLOAD_DIR`, `OUTPUT_DIR`

---

## 핵심 데이터 흐름

```
[1] POST /api/analyze
    PDF 파일 + 옵션
    → pdf_parser.resolve_page_selection()   # 페이지 범위 해석
    → pdf_parser.extract_pdf_images()       # PDF 내 이미지 추출 → uploads/assets_{uid}/
    → claude_analyzer.analyze_pdf()         # Claude API → slides JSON
    → slide_quality.review_slides()         # 품질 검사 + content_kind 추론
    → slide_enricher.attach_pdf_images()    # 이미지를 슬라이드에 매핑
    → 응답: { slides, outline, quality, assets, uid }

[2] POST /api/generate
    { slides, design, assets, pdf_name }
    → slide_quality.review_slides()         # 재검토
    → slide_enricher.attach_pdf_images()    # 이미지 재매핑
    → ppt_generator.generate_pptx()        # .pptx 생성
    → outputs/{uid}_slides.json 저장       # 미리보기용 payload
    → 응답: { filename, preview_uid, slide_count, preset, download_name }

[3] GET /preview/<uid>          → preview.html (클라이언트가 /api/slides/<uid> 호출)
[4] GET /api/slides/<uid>       → {uid}_slides.json 반환
[5] POST /api/slides/<uid>/update → 슬라이드 수정 후 .pptx 재생성
[6] GET /download/<filename>    → .pptx 파일 전송
```

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
    "content_kind": "explain|process|compare|case|data",  ← slide_quality가 추론
    "image_bundle_uid": "abc12345",                       ← slide_enricher가 매핑
    "image_asset_name": "img_001.png",
    "image_page": 7
  },
  { "type": "summary", "title": "핵심 요약", "points": ["요약1", "요약2"] }
]
```

**content_kind** (slide_quality.py가 자동 추론):
- `explain`: 일반 설명 (기본값)
- `process`: 단계/절차 흐름
- `compare`: 두 관점 비교
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
  "slide_number": true,
  "content_layout": "classic"
}
```

- `preset`: 8종 중 하나 (`corporate` | `startup` | `academic` | `creative` | `terra` | `mono` | `forest` | `pastel`)
- `primary_color` / `accent_color`: hex 문자열로 override. null이면 preset 색상 사용
- `logo_uid`: `/api/upload-logo` 응답의 uid. `uploads/logo_{uid}.{ext}` 경로로 저장됨
- `content_layout`: content 슬라이드 레이아웃 전역 설정 (`classic` | `split` | `card` | `highlight`)
- 하위 호환: `theme` 문자열 전달 시 `_coerce_design()`이 자동으로 design 객체로 변환

---

## API 엔드포인트 목록

| 메서드 | 경로 | 설명 |
|--------|------|------|
| GET | `/` | 메인 페이지 |
| GET | `/preview/<uid>` | 슬라이드 뷰어 페이지 |
| POST | `/api/analyze` | PDF 분석 → slides JSON |
| POST | `/api/generate` | slides → .pptx 생성 |
| GET | `/api/slides/<uid>` | 저장된 슬라이드 payload 반환 |
| POST | `/api/slides/<uid>/update` | 슬라이드 수정 후 pptx 재생성 |
| POST | `/api/review-slides` | 슬라이드 품질 검사만 수행 |
| GET | `/api/presets` | 디자인 프리셋 목록 반환 |
| GET | `/api/fonts` | 지원 폰트 목록 반환 |
| GET | `/api/capabilities` | 서버 기능 (OCR 여부 등) |
| POST | `/api/upload-logo` | 로고 이미지 업로드 |
| GET | `/api/logo/<logo_uid>` | 로고 이미지 반환 |
| GET | `/api/pdf-asset/<bundle_uid>/<asset_name>` | PDF에서 추출한 이미지 반환 |
| GET | `/api/history` | 생성 히스토리 |
| GET | `/download/<filename>` | .pptx 다운로드 |

---

## 모듈별 역할 상세

### core/claude_analyzer.py
- `analyze_pdf(pdf_path, slide_count, page_range, extra_prompt)` → slides list
- 100페이지 이하: 단일 Claude API 호출
- 100페이지 초과: 청크별 요약(`CHUNK_SYSTEM_PROMPT`) → 종합(`FINAL_SYSTEM_PROMPT`) 2단계
- 슬라이드 JSON에 `layout`, `source_pages` 필드를 Claude가 직접 채움

### core/pdf_parser.py
- `resolve_page_selection(pdf_path, page_hint, max_pages_per_chunk)` → page_plan dict
  - 숫자 범위("1-5, 8") → `parse_page_range()`
  - 텍스트 힌트("서론 부분") → `select_pages_by_text_hint()` (TF-IDF 유사 점수 계산)
  - 힌트 없음 → 전체 페이지
- `extract_pdf_images()` → PDF 내 이미지 추출, `uploads/assets_{uid}/` 저장
- `extract_pages_as_bytes()` → 특정 페이지만 포함한 PDF bytes 반환

### core/ppt_generator.py
- `generate_pptx(slides_data, output_path, design, resolved_assets)` → .pptx
- `_resolve_theme(design)` → PRESETS + brand override → Resolved Theme dict
- 슬라이드 타입별 렌더 함수: `_title_slide`, `_agenda_slide`, `_content_slide`, `_summary_slide`
- content_layout별 렌더 함수: `_content_slide_classic`, `_split`, `_card`, `_highlight`, `_process`, `_compare`
- `PRESETS`: 8종 프리셋 (색상 팔레트 + header_style + bullet_style + density)
- `LEGACY_THEME_PRESET_MAP`: 기존 navy/terra/mono/forest → 새 preset ID 매핑
- `SUPPORTED_FONTS`: 지원 폰트 목록

### core/slide_quality.py
- `review_slides(slides_data, selected_pages)` → 품질 검사 + 보정
  - `infer_content_kind()`: 키워드 기반 content_kind 자동 추론
  - `_kind_layout()`: content_kind에 맞게 layout 필드 보정
  - `_normalize_source_pages()`: source_pages 정규화
  - `_dedupe_points()`: 중복 포인트 제거
  - `_ensure_notes()`: 발표자 노트 없으면 자동 생성
- `build_outline(slides)` → 슬라이드 목차 구조 반환
- `build_quality_summary(slides)` → 품질 경고 목록 반환

### core/slide_enricher.py
- `attach_pdf_images_to_slides(slides, assets)` → 이미지-슬라이드 매핑
- `source_pages` 기준으로 같은 페이지 이미지 우선 매칭
- 이미 매핑된 이미지 재사용 방지 (used_asset_keys 추적)

---

## 파일 저장 구조

```
uploads/
├── {uid}.pdf                        # 분석 중 임시 PDF (완료 후 삭제)
├── {uid}_ocr.pdf                    # OCR 처리된 PDF (완료 후 삭제)
├── logo_{uid}.{ext}                 # 업로드된 로고 (영구 보관)
└── assets_{uid}/
    ├── img_001.png                  # PDF에서 추출한 이미지들
    └── img_002.png

outputs/
├── {base_name}_{uid}.pptx           # 생성된 PPT 파일
└── {uid}_slides.json                # 미리보기용 payload (slides+design+assets)
```

`{uid}_slides.json` 저장 구조:
```json
{
  "slides": [...],
  "outline": [...],
  "quality": {...},
  "design": {...},
  "assets": [...],
  "page_plan": {...},
  "pdf_name": "강의자료.pdf",
  "filename": "강의자료_abc12345.pptx",
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
- OCR 기능(ocrmypdf + tesseract)은 선택적 — `OCR_AVAILABLE`로 체크 후 사용.

---

## 진행 중인 작업

- **CODEX_SPEC.md** 참고: 디자인 시스템 3종 기능(프리셋 8종, 브랜드 커스터마이저, 레이아웃 4종)이 백엔드에는 구현되어 있고, 프론트엔드 UI 연동 작업 진행 중.
- `ppt_generator.py`의 `process`, `compare` 레이아웃 렌더러 구현 완성 필요.
- `preview.html` 우측 에디터 패널: 슬라이드 내용 직접 편집 + `/api/slides/<uid>/update` 연동.
