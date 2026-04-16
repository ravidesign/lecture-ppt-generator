# PDF → PPT 강의 교안 생성기 — 디자인 시스템 업그레이드 스펙

## 0. 개요

이 문서는 기존 Flask + Claude API 기반 PPT 생성기에 **3가지 디자인 제어 기능**을 추가하는 작업 명세서다.
CODEX는 이 문서만 보고 구현을 완료할 수 있어야 한다.

### 추가할 기능

| 기능 | 설명 |
|---|---|
| **A. 디자인 컨셉 프리셋** | 색상+레이아웃+장식 스타일을 묶은 8종 프리셋 |
| **B. 브랜드 커스터마이저** | Primary/Accent 컬러, 폰트, 회사명, 로고, 푸터 |
| **C. 콘텐츠 레이아웃 스타일** | content 슬라이드 레이아웃 4종 선택 |

---

## 1. 현재 프로젝트 구조

```
pdf-to-ppt/
├── app.py                  # Flask 앱 (라우터)
├── core/
│   ├── claude_analyzer.py  # PDF → Claude API → slides JSON
│   ├── ppt_generator.py    # slides JSON → .pptx 파일
│   ├── pdf_parser.py       # 페이지 범위 추출 (PyMuPDF)
│   └── history.py          # 히스토리 저장/조회
├── templates/
│   ├── index.html          # 메인 UI
│   └── preview.html        # 슬라이드 뷰어
├── uploads/                # 업로드된 PDF 임시 저장
├── outputs/                # 생성된 .pptx + _slides.json
└── requirements.txt
```

### 현재 핵심 데이터 흐름

```
[POST /api/analyze]  PDF + slide_count + page_range + extra_prompt
    → claude_analyzer.analyze_pdf()
    → slides: List[dict]  (type/title/points/notes/items)

[POST /api/generate]  slides + theme(str) + pdf_name
    → ppt_generator.generate_pptx(slides_data, output_path, theme)
    → .pptx 파일 생성 + {uid}_slides.json 저장

[GET /preview/<uid>]  → preview.html
[GET /api/slides/<uid>]  → {uid}_slides.json 반환
```

### 현재 ppt_generator.py THEMES 구조

```python
THEMES = {
    "navy": {
        "name": "네이비 클래식",
        "header":  RGBColor(0x1E, 0x3A, 0x5F),
        "accent":  RGBColor(0x4A, 0x90, 0xD9),
        "confirm": RGBColor(0x1D, 0x9E, 0x75),
        "light":   RGBColor(0xEB, 0xF2, 0xFA),
        "bg":      RGBColor(0xFF, 0xFF, 0xFF),
        "text":    RGBColor(0x1A, 0x22, 0x33),
        "title_sub": RGBColor(0xA8, 0xC8, 0xE8),
        "title_dark": RGBColor(0x15, 0x2B, 0x4A),
    },
    # terra, mono, forest 동일 구조
}
```

---

## 2. 구현할 데이터 모델

### 2-1. Design Config (핵심 구조체)

`/api/generate`에 전달되는 `design` 필드. 기존 `theme` 문자열을 이 객체로 교체.

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

| 필드 | 타입 | 기본값 | 설명 |
|---|---|---|---|
| `preset` | str | `"corporate"` | A. 프리셋 ID |
| `primary_color` | str \| null | null | B. 헤더 색상 override (hex, 예: `"#1E3A5F"`) |
| `accent_color` | str \| null | null | B. 강조 색상 override (hex) |
| `font_name` | str | `"Malgun Gothic"` | B. 전체 폰트 |
| `company_name` | str | `""` | B. 타이틀 슬라이드 하단 삽입 |
| `presenter_name` | str | `""` | B. 타이틀 슬라이드 하단 삽입 |
| `logo_uid` | str \| null | null | B. 로고 파일 uid (업로드 후 반환값) |
| `footer_text` | str | `""` | B. 모든 슬라이드 하단 텍스트 |
| `slide_number` | bool | true | B. 슬라이드 번호 표시 여부 |
| `content_layout` | str | `"classic"` | C. content 슬라이드 레이아웃 ID |

### 2-2. Resolved Theme (내부 처리용)

`generate_pptx` 내부에서 Design Config를 해석해 만드는 최종 딕셔너리.
python-pptx 함수들은 이 딕셔너리를 `t`로 받는다.

```python
t = {
    # 색상 (RGBColor)
    "header":     RGBColor(...),
    "accent":     RGBColor(...),
    "confirm":    RGBColor(...),
    "light":      RGBColor(...),
    "bg":         RGBColor(...),
    "text":       RGBColor(...),
    "title_sub":  RGBColor(...),
    "title_dark": RGBColor(...),

    # 스타일 (문자열)
    "header_style":   "full",       # full | left_bar | bottom_line
    "bullet_style":   "circle",     # circle | square | number | dash
    "density":        "standard",   # compact | standard | spacious
    "content_layout": "classic",    # classic | split | card | highlight

    # 브랜드 (문자열/bool/None)
    "font_name":      "Malgun Gothic",
    "company_name":   "",
    "presenter_name": "",
    "logo_path":      None,         # 절대 경로 또는 None
    "footer_text":    "",
    "slide_number":   True,
}
```

---

## 3. Feature A — 디자인 컨셉 프리셋 8종

### 3-1. PRESETS 딕셔너리 (ppt_generator.py에 추가)

기존 `THEMES` 옆에 `PRESETS`를 새로 정의. `THEMES`는 하위 호환용으로 유지.

```python
PRESETS = {
    "corporate": {
        "name": "코퍼레이트",
        "desc": "격식 있는 기업 강의용. 안정적이고 신뢰감 있는 구성.",
        "colors": {
            "header":     (0x1E, 0x3A, 0x5F),
            "accent":     (0x4A, 0x90, 0xD9),
            "confirm":    (0x1D, 0x9E, 0x75),
            "light":      (0xEB, 0xF2, 0xFA),
            "bg":         (0xFF, 0xFF, 0xFF),
            "text":       (0x1A, 0x22, 0x33),
            "title_sub":  (0xA8, 0xC8, 0xE8),
            "title_dark": (0x15, 0x2B, 0x4A),
        },
        "header_style": "full",
        "bullet_style": "circle",
        "density": "standard",
    },
    "startup": {
        "name": "스타트업",
        "desc": "대담하고 현대적인 스타트업 피치 스타일.",
        "colors": {
            "header":     (0x0F, 0x17, 0x2A),
            "accent":     (0x6C, 0x63, 0xFF),
            "confirm":    (0x2D, 0xD4, 0xBF),
            "light":      (0xF0, 0xEF, 0xFF),
            "bg":         (0xFA, 0xFA, 0xFD),
            "text":       (0x11, 0x18, 0x27),
            "title_sub":  (0xA0, 0x9C, 0xFF),
            "title_dark": (0x07, 0x0D, 0x1C),
        },
        "header_style": "bottom_line",
        "bullet_style": "square",
        "density": "spacious",
    },
    "academic": {
        "name": "아카데믹",
        "desc": "학술/교육 자료. 정보 밀도 높고 깔끔한 레이아웃.",
        "colors": {
            "header":     (0x2C, 0x3E, 0x50),
            "accent":     (0xE7, 0x4C, 0x3C),
            "confirm":    (0x27, 0xAE, 0x60),
            "light":      (0xEC, 0xF0, 0xF1),
            "bg":         (0xFF, 0xFF, 0xFF),
            "text":       (0x1A, 0x1A, 0x1A),
            "title_sub":  (0xBD, 0xC3, 0xC7),
            "title_dark": (0x1A, 0x28, 0x35),
        },
        "header_style": "left_bar",
        "bullet_style": "dash",
        "density": "compact",
    },
    "creative": {
        "name": "크리에이티브",
        "desc": "디자인/마케팅 분야. 생동감 있고 개성 강한 스타일.",
        "colors": {
            "header":     (0xFF, 0x6B, 0x6B),
            "accent":     (0xFF, 0xE6, 0x6D),
            "confirm":    (0x4E, 0xCD, 0xC4),
            "light":      (0xFF, 0xF5, 0xF5),
            "bg":         (0xFF, 0xFF, 0xFF),
            "text":       (0x2D, 0x2D, 0x2D),
            "title_sub":  (0xFF, 0xC8, 0xC8),
            "title_dark": (0xCC, 0x44, 0x44),
        },
        "header_style": "full",
        "bullet_style": "number",
        "density": "spacious",
    },
    "terra": {
        "name": "테라코타",
        "desc": "따뜻하고 자연스러운 분위기. 인문/예술 강의에 적합.",
        "colors": {
            "header":     (0x7A, 0x3B, 0x2E),
            "accent":     (0xC8, 0x6B, 0x4A),
            "confirm":    (0xD4, 0x9A, 0x3A),
            "light":      (0xFD, 0xF0, 0xE8),
            "bg":         (0xFF, 0xFB, 0xF7),
            "text":       (0x2C, 0x1A, 0x12),
            "title_sub":  (0xF0, 0xC4, 0xA8),
            "title_dark": (0x5A, 0x2A, 0x1E),
        },
        "header_style": "full",
        "bullet_style": "circle",
        "density": "standard",
    },
    "mono": {
        "name": "모노 미니멀",
        "desc": "흑백 모노톤. 텍스트 중심의 미니멀 디자인.",
        "colors": {
            "header":     (0x18, 0x18, 0x18),
            "accent":     (0x58, 0x58, 0x58),
            "confirm":    (0x38, 0x38, 0x38),
            "light":      (0xF2, 0xF2, 0xF2),
            "bg":         (0xFF, 0xFF, 0xFF),
            "text":       (0x1A, 0x1A, 0x1A),
            "title_sub":  (0xB8, 0xB8, 0xB8),
            "title_dark": (0x0A, 0x0A, 0x0A),
        },
        "header_style": "bottom_line",
        "bullet_style": "dash",
        "density": "standard",
    },
    "forest": {
        "name": "포레스트",
        "desc": "자연/환경/웰니스. 차분하고 신뢰감 있는 초록 계열.",
        "colors": {
            "header":     (0x1C, 0x40, 0x2E),
            "accent":     (0x2E, 0x7D, 0x52),
            "confirm":    (0x5A, 0xA8, 0x6A),
            "light":      (0xE8, 0xF5, 0xED),
            "bg":         (0xF7, 0xFC, 0xF8),
            "text":       (0x12, 0x2A, 0x1C),
            "title_sub":  (0xA0, 0xCC, 0xB4),
            "title_dark": (0x10, 0x2A, 0x1C),
        },
        "header_style": "full",
        "bullet_style": "circle",
        "density": "standard",
    },
    "pastel": {
        "name": "소프트 파스텔",
        "desc": "부드럽고 친근한 분위기. 아동/청소년 교육이나 워크숍.",
        "colors": {
            "header":     (0x7E, 0x57, 0xC2),
            "accent":     (0xF0, 0x6A, 0xA1),
            "confirm":    (0x26, 0xC6, 0xDA),
            "light":      (0xF3, 0xE5, 0xF5),
            "bg":         (0xFF, 0xFF, 0xFF),
            "text":       (0x31, 0x27, 0x3F),
            "title_sub":  (0xD1, 0xC4, 0xE9),
            "title_dark": (0x51, 0x2D, 0xA8),
        },
        "header_style": "left_bar",
        "bullet_style": "circle",
        "density": "spacious",
    },
}
```

### 3-2. 헤더 스타일 3종 (content/agenda 슬라이드에 적용)

| ID | 설명 | 구현 방법 |
|---|---|---|
| `full` | 전체 너비 색상 헤더 바 (현재 방식) | `_rect(s, 0, 0, 13.33, 1.28, t["header"])` |
| `left_bar` | 좌측 세로 accent 바 + 제목은 회색 배경 없이 본문 영역 상단 | 세로 바 `_rect(s, 0, 0, 0.22, 7.5, t["accent"])` + 타이틀 텍스트 `t["header"]` 색으로 |
| `bottom_line` | 헤더 배경 없음, 타이틀 아래 accent 언더라인만 | 배경 없음, `_rect(s, 0.5, 1.1, 12.33, 0.05, t["accent"])` |

### 3-3. 불릿 스타일 5종 (content 슬라이드 포인트에 적용)

| ID | 구현 방법 |
|---|---|
| `circle` | `slide.shapes.add_shape(9, ...)` (타원, MSO_SHAPE_TYPE 9) |
| `square` | `slide.shapes.add_shape(1, ...)` (직사각형, w=h=0.18 Inches) |
| `number` | 텍스트박스에 숫자 문자열, accent 색 배경 직사각형 위에 흰 텍스트 |
| `dash` | `_rect(s, x, y+0.16, 0.20, 0.04, t["accent"])` (얇은 가로선) |

---

## 4. Feature B — 브랜드 커스터마이저

### 4-1. 로고 업로드 API (신규)

**엔드포인트**: `POST /api/upload-logo`  
**요청**: multipart/form-data, 필드명 `logo`  
**지원 확장자**: png, jpg, jpeg, gif, webp  
**저장 경로**: `uploads/logo_{uid}.{ext}`

```python
@app.route("/api/upload-logo", methods=["POST"])
def api_upload_logo():
    f = request.files.get("logo")
    if not f:
        return jsonify({"error": "파일 없음"}), 400
    ext = f.filename.rsplit(".", 1)[-1].lower()
    if ext not in {"png", "jpg", "jpeg", "gif", "webp"}:
        return jsonify({"error": "이미지 파일만 지원"}), 400
    uid = uuid.uuid4().hex[:8]
    logo_path = os.path.join(UPLOAD_DIR, f"logo_{uid}.{ext}")
    f.save(logo_path)
    return jsonify({"ok": True, "logo_uid": uid, "ext": ext})
```

**응답**:
```json
{"ok": true, "logo_uid": "a1b2c3d4", "ext": "png"}
```

### 4-2. 로고를 슬라이드에 삽입 (ppt_generator.py)

로고가 있을 때 **모든 슬라이드 우측 상단**에 삽입.  
삽입 위치: x=12.0, y=0.12, w=1.1, h=0.8 Inches (헤더 영역 내)

```python
from pptx.util import Inches
from PIL import Image  # pillow 패키지 필요 (requirements.txt에 추가)

def _add_logo(slide, logo_path: str):
    """슬라이드 우측 상단에 로고 삽입. 종횡비 유지."""
    if not logo_path or not os.path.exists(logo_path):
        return
    try:
        with Image.open(logo_path) as img:
            iw, ih = img.size
        max_w = Inches(1.1)
        max_h = Inches(0.78)
        ratio = min(max_w / iw, max_h / ih)
        w = int(iw * ratio)
        h = int(ih * ratio)
        x = Inches(13.33) - w - Inches(0.15)
        y = Inches(0.12)
        slide.shapes.add_picture(logo_path, x, y, w, h)
    except Exception:
        pass  # 로고 삽입 실패 시 무시
```

> **주의**: Pillow가 없으면 PIL import가 실패한다. `requirements.txt`에 `Pillow>=10.0.0` 추가.

### 4-3. 회사명 / 발표자명 삽입 (타이틀 슬라이드)

타이틀 슬라이드 하단 어두운 바(`title_dark` 배경)에 삽입.
- 회사명: 우측 정렬, 흰색, 14pt
- 발표자명: 우측 정렬, `title_sub` 색, 12pt

```python
# _title_slide 함수 내부 마지막에 추가
if t.get("company_name"):
    _tb(s, 0.8, 6.15, 11.5, 0.55, t["company_name"],
        14, bold=True, color=RGBColor(0xFF,0xFF,0xFF), align=PP_ALIGN.RIGHT)
if t.get("presenter_name"):
    _tb(s, 0.8, 6.65, 11.5, 0.45, t["presenter_name"],
        12, color=t["title_sub"], align=PP_ALIGN.RIGHT)
```

### 4-4. 푸터 + 슬라이드 번호 (content/agenda/summary 슬라이드)

모든 비-타이틀 슬라이드 맨 아래 `light` 색 바 위에 렌더링.

```python
def _add_footer(slide, slide_index: int, t: dict):
    """슬라이드 하단 푸터 바에 텍스트와 번호 삽입."""
    footer_text = t.get("footer_text", "")
    show_num = t.get("slide_number", True)

    if footer_text:
        _tb(slide, 0.4, 6.9, 8.0, 0.45, footer_text,
            9, color=t["accent"], align=PP_ALIGN.LEFT)
    if show_num:
        _tb(slide, 11.0, 6.9, 2.0, 0.45, str(slide_index),
            9, color=t["text"], align=PP_ALIGN.RIGHT)
```

`slide_index`는 `generate_pptx` 루프에서 순서를 전달 (`enumerate` 사용).

### 4-5. 폰트 적용

`_tb` 함수 내부의 `run.font.name = "Malgun Gothic"` 을  
`run.font.name = t.get("font_name", "Malgun Gothic")` 으로 교체.

**지원 폰트 목록** (프론트엔드 드롭다운용):
```python
SUPPORTED_FONTS = [
    {"id": "Malgun Gothic",  "label": "맑은 고딕"},
    {"id": "NanumGothic",    "label": "나눔고딕"},
    {"id": "NanumBarunGothic","label": "나눔바른고딕"},
    {"id": "NanumMyeongjo", "label": "나눔명조"},
    {"id": "Pretendard",     "label": "프리텐다드"},
    {"id": "Apple SD Gothic Neo", "label": "애플 SD 고딕"},
]
```

> 참고: python-pptx는 `font.name`을 문자열로만 저장한다. 해당 폰트가 로컬에 설치된 경우 PowerPoint에서 정상 렌더링. 없으면 기본 폰트로 fallback.

---

## 5. Feature C — 콘텐츠 레이아웃 스타일 4종

`content` 타입 슬라이드에만 적용. `title`, `agenda`, `summary`는 레이아웃 고정.

### 5-1. `classic` (현재 방식)

```
[────────────────── 헤더 ──────────────────]
[accent 언더라인]
● 포인트 1
● 포인트 2
● 포인트 3
● 포인트 4
● 포인트 5
[──────── 하단 푸터 바 ────────────────────]
```

현재 `_content_slide` 함수 그대로.

### 5-2. `split`

```
[────────────────── 헤더 ──────────────────]
│              │                           │
│   슬라이드   │  ● 포인트 1              │
│   제목       │  ● 포인트 2              │
│   (큰 글씨) │  ● 포인트 3              │
│              │  ● 포인트 4              │
│   부제목     │                           │
[──────── 하단 푸터 바 ────────────────────]
```

구현:
- 좌측 컬럼: x=0 ~ 4.5 Inches, `header` 색 배경
- 우측 컬럼: x=4.5 ~ 13.33 Inches, `bg` 색 배경
- 헤더 영역 없음 (좌측 컬럼이 헤더 역할)
- 슬라이드 `title`은 좌측에 세로 중앙 정렬, 흰색 26pt
- 포인트들은 우측 컬럼에 세로 배치

```python
def _content_slide_split(prs, data, t, slide_index):
    s = prs.slides.add_slide(prs.slide_layouts[6])
    _set_bg(s, t["bg"])
    # 좌측 컬럼 배경
    _rect(s, 0, 0, 4.5, 7.5, t["header"])
    # 좌측에 제목
    _tb(s, 0.3, 1.8, 3.8, 2.2, data.get("title", ""),
        24, bold=True, color=RGBColor(0xFF,0xFF,0xFF))
    # 구분선
    _rect(s, 4.5, 0.5, 0.05, 6.5, t["accent"])
    # 우측 포인트
    for i, pt in enumerate(data.get("points", [])[:5]):
        y = 1.2 + i * 0.9
        _bullet(s, 4.9, y, pt, t, i)  # _bullet은 bullet_style에 따라 분기하는 헬퍼
    _add_footer(s, slide_index, t)
    _add_logo(s, t.get("logo_path"))
    if data.get("notes"):
        s.notes_slide.notes_text_frame.text = data["notes"]
```

### 5-3. `card`

```
[────────────────── 헤더 ──────────────────]
┌─────────────┐ ┌─────────────┐ ┌─────────┐
│  포인트 1   │ │  포인트 2   │ │포인트 3 │
└─────────────┘ └─────────────┘ └─────────┘
┌─────────────┐ ┌─────────────┐
│  포인트 4   │ │  포인트 5   │
└─────────────┘ └─────────────┘
[──────── 하단 푸터 바 ────────────────────]
```

구현:
- 포인트를 최대 5개, 행당 3개 배치
- 각 카드: `light` 색 배경 직사각형 + 상단 4px `accent` 색 강조바 + 텍스트
- 카드 크기: w=4.0, h=1.6 Inches
- 1행: y=1.55, 2행: y=3.3

```python
CARD_COLS = 3
CARD_W, CARD_H = 4.0, 1.6
CARD_GAP = 0.2
CARD_START_X = 0.37
CARD_ROW1_Y = 1.55
CARD_ROW2_Y = 3.3

def _content_slide_card(prs, data, t, slide_index):
    s = prs.slides.add_slide(prs.slide_layouts[6])
    _set_bg(s, t["bg"])
    _render_header(s, data, t)  # header_style에 따라 분기하는 헬퍼

    pts = data.get("points", [])[:5]
    for i, pt in enumerate(pts):
        col = i % CARD_COLS
        row = i // CARD_COLS
        x = CARD_START_X + col * (CARD_W + CARD_GAP)
        y = CARD_ROW1_Y if row == 0 else CARD_ROW2_Y

        _rect(s, x, y, CARD_W, CARD_H, t["light"])
        _rect(s, x, y, CARD_W, 0.07, t["accent"])  # 상단 accent 바
        _tb(s, x+0.18, y+0.22, CARD_W-0.3, CARD_H-0.3,
            pt, 13, color=t["text"])

    _add_footer(s, slide_index, t)
    _add_logo(s, t.get("logo_path"))
    if data.get("notes"):
        s.notes_slide.notes_text_frame.text = data["notes"]
```

### 5-4. `highlight`

```
[────────────────── 헤더 ──────────────────]
┌──────────────────────────────────────────┐
│  포인트 1 (크게, accent 색, 28pt)       │
│  ─────────────────────────────────────── │
└──────────────────────────────────────────┘
  ● 포인트 2  ● 포인트 3  ● 포인트 4
[──────── 하단 푸터 바 ────────────────────]
```

구현:
- 첫 번째 포인트: `accent` 색 박스 배경, 큰 글씨(24pt), 흰색 텍스트, 전체 너비
- 나머지 포인트: 하단에 인라인으로 작게 (12pt, 3열)

```python
def _content_slide_highlight(prs, data, t, slide_index):
    s = prs.slides.add_slide(prs.slide_layouts[6])
    _set_bg(s, t["bg"])
    _render_header(s, data, t)

    pts = data.get("points", [])
    if pts:
        # 첫 번째 포인트 강조 블록
        _rect(s, 0.5, 1.55, 12.33, 2.0, t["accent"])
        _tb(s, 0.75, 1.75, 11.8, 1.6, pts[0],
            24, bold=True, color=RGBColor(0xFF,0xFF,0xFF))

    # 나머지 포인트 (작게, 3열)
    remaining = pts[1:4]
    col_w = 12.33 / max(len(remaining), 1)
    for i, pt in enumerate(remaining):
        x = 0.5 + i * col_w
        _rect(s, x+0.05, 3.9, col_w-0.15, 1.4, t["light"])
        _tb(s, x+0.2, 4.0, col_w-0.3, 1.2, pt, 12, color=t["text"])

    _add_footer(s, slide_index, t)
    _add_logo(s, t.get("logo_path"))
    if data.get("notes"):
        s.notes_slide.notes_text_frame.text = data["notes"]
```

---

## 6. ppt_generator.py 전체 리팩토링 명세

### 6-1. 추가/수정할 함수 목록

```python
# 신규 유틸 함수
def _hex_to_rgb(hex_str: str) -> RGBColor       # "#1E3A5F" → RGBColor(0x1E, 0x3A, 0x5F)
def _resolve_theme(design: dict) -> dict          # Design Config → Resolved Theme
def _render_header(slide, data, t)                # header_style에 따라 분기
def _add_bullet(slide, x, y, pt, t, index)        # bullet_style에 따라 분기
def _add_footer(slide, slide_index, t)            # 푸터 + 슬라이드 번호
def _add_logo(slide, logo_path)                   # 로고 삽입

# 수정할 함수
def _tb(slide, x, y, w, h, text, size, bold=False, color=None, align=PP_ALIGN.LEFT, wrap=True, font_name="Malgun Gothic")
def _title_slide(prs, data, t, slide_index)       # 회사명/발표자명/로고 추가
def _agenda_slide(prs, data, t, slide_index)      # 헤더스타일/로고/푸터 적용
def _content_slide(prs, data, t, slide_index)     # content_layout 분기
def _summary_slide(prs, data, t, slide_index)     # 로고/푸터 적용

# 메인 함수 시그니처 변경
def generate_pptx(slides_data: list, output_path: str, design: dict) -> str
```

### 6-2. `_resolve_theme` 구현

```python
def _hex_to_rgb(hex_str: str) -> RGBColor:
    h = hex_str.lstrip("#")
    return RGBColor(int(h[0:2],16), int(h[2:4],16), int(h[4:6],16))

def _resolve_theme(design: dict) -> dict:
    preset_id = design.get("preset", "corporate")
    p = PRESETS.get(preset_id, PRESETS["corporate"])

    # 기본 팔레트는 preset에서
    t = {k: RGBColor(*v) for k, v in p["colors"].items()}

    # Brand color override
    if design.get("primary_color"):
        t["header"]     = _hex_to_rgb(design["primary_color"])
        t["title_dark"] = _hex_to_rgb(design["primary_color"])  # 약간 어둡게 하는 것이 이상적이나 동일 사용

    if design.get("accent_color"):
        t["accent"]  = _hex_to_rgb(design["accent_color"])
        t["confirm"] = _hex_to_rgb(design["accent_color"])

    # 스타일 메타
    t["header_style"]   = p.get("header_style", "full")
    t["bullet_style"]   = p.get("bullet_style", "circle")
    t["density"]        = p.get("density", "standard")
    t["content_layout"] = design.get("content_layout", "classic")

    # 브랜드 정보
    t["font_name"]      = design.get("font_name", "Malgun Gothic")
    t["company_name"]   = design.get("company_name", "")
    t["presenter_name"] = design.get("presenter_name", "")
    t["footer_text"]    = design.get("footer_text", "")
    t["slide_number"]   = design.get("slide_number", True)

    # 로고 경로 해석
    logo_uid = design.get("logo_uid")
    t["logo_path"] = None
    if logo_uid:
        for ext in ["png","jpg","jpeg","gif","webp"]:
            candidate = os.path.join(UPLOAD_DIR, f"logo_{logo_uid}.{ext}")
            if os.path.exists(candidate):
                t["logo_path"] = candidate
                break

    return t
```

### 6-3. `generate_pptx` 수정

```python
def generate_pptx(slides_data: list, output_path: str, design: dict) -> str:
    prs = Presentation()
    prs.slide_width = SLIDE_W
    prs.slide_height = SLIDE_H

    t = _resolve_theme(design)

    content_layout = t["content_layout"]
    content_handlers = {
        "classic":   _content_slide_classic,
        "split":     _content_slide_split,
        "card":      _content_slide_card,
        "highlight": _content_slide_highlight,
    }
    content_fn = content_handlers.get(content_layout, _content_slide_classic)

    for idx, slide_data in enumerate(slides_data, start=1):
        stype = slide_data.get("type", "content")
        if stype == "title":
            _title_slide(prs, slide_data, t, idx)
        elif stype == "agenda":
            _agenda_slide(prs, slide_data, t, idx)
        elif stype == "summary":
            _summary_slide(prs, slide_data, t, idx)
        else:
            content_fn(prs, slide_data, t, idx)

    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    prs.save(output_path)
    return output_path
```

---

## 7. app.py 변경 명세

### 7-1. `/api/generate` 수정

**요청 body 변경**:

기존:
```json
{"slides": [...], "theme": "navy", "pdf_name": "강의자료.pdf"}
```

신규:
```json
{
  "slides": [...],
  "design": { "preset": "corporate", "primary_color": null, ... },
  "pdf_name": "강의자료.pdf"
}
```

**하위 호환 처리** (기존 `theme` 필드가 오면 자동 변환):
```python
design = body.get("design")
if design is None:
    # 하위 호환: 기존 theme 문자열을 design으로 변환
    old_theme = body.get("theme", "navy")
    design = {"preset": old_theme}
```

**슬라이드 JSON 저장 시 design도 포함**:
```python
json.dump({
    "slides": slides_data,
    "design": design,
    "pdf_name": pdf_name,
    "filename": output_filename,
}, f, ensure_ascii=False)
```

**`generate_pptx` 호출 변경**:
```python
generate_pptx(slides_data, output_path, design)
```

**응답에 preset name 포함**:
```python
preset_name = PRESETS.get(design.get("preset","corporate"), {}).get("name", "코퍼레이트")
return jsonify({
    "ok": True,
    "filename": output_filename,
    "preview_uid": uid,
    "slide_count": len(slides_data),
    "preset": preset_name,
})
```

### 7-2. `/api/presets` 신규

```python
@app.route("/api/presets")
def api_presets():
    from core.ppt_generator import PRESETS
    result = []
    for pid, p in PRESETS.items():
        c = p["colors"]
        result.append({
            "id": pid,
            "name": p["name"],
            "desc": p["desc"],
            "swatch": {
                "header":  "#{:02X}{:02X}{:02X}".format(*c["header"]),
                "accent":  "#{:02X}{:02X}{:02X}".format(*c["accent"]),
                "bg":      "#{:02X}{:02X}{:02X}".format(*c["bg"]),
            },
            "header_style": p["header_style"],
            "bullet_style": p["bullet_style"],
        })
    return jsonify(result)
```

### 7-3. `/api/upload-logo` 신규

위 4-1 항목 참고.

### 7-4. `/api/fonts` 신규 (선택)

```python
@app.route("/api/fonts")
def api_fonts():
    from core.ppt_generator import SUPPORTED_FONTS
    return jsonify(SUPPORTED_FONTS)
```

---

## 8. frontend (index.html) 변경 명세

### 8-1. 새로운 UI 섹션 위치

업로드 → 옵션(슬라이드 수/기존 테마 제거) → **디자인 설정 (3섹션)** → 페이지 범위 → 추가 지시사항 → 분석 시작 버튼

### 8-2. 디자인 설정 UI 구조

파일 선택 후(`setF` 함수 내) 표시되는 카드. 내부에 3개 탭으로 구성.

```
┌─────────────────────────────────────────┐
│ DESIGN SETTINGS                         │
│ [A 컨셉] [B 브랜드] [C 레이아웃]  ← 탭 │
│─────────────────────────────────────────│
│  (각 탭 내용)                           │
└─────────────────────────────────────────┘
```

**탭 A: 디자인 컨셉** (`/api/presets`로 동적 로딩)

```
8종 프리셋 그리드 (4열×2행):
┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐
│ ■■ 컬러  │ │ ■■ 컬러  │ ...
│ 코퍼레이트│ │ 스타트업  │
│ 격식있는  │ │ 대담하고  │
└──────────┘ └──────────┘

각 카드: header 색 정사각형 + accent 색 도트 + bg 색 배경 + 이름 + 한줄 설명
선택 시: 파란 테두리 표시
```

**탭 B: 브랜드 커스터마이저**

```
Primary Color  [──────────] [컬러피커] (hex input + color input type=color)
Accent Color   [──────────] [컬러피커]
폰트           [드롭다운 ▼]
회사명         [텍스트 입력]
발표자/강사    [텍스트 입력]
로고           [파일 선택 버튼] → 업로드 즉시 /api/upload-logo 호출
푸터 텍스트    [텍스트 입력]
슬라이드 번호  [토글 스위치]
```

**탭 C: 콘텐츠 레이아웃**

4종 레이아웃 카드 (다이어그램으로 표현):

```
┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐
│ ■■■■■■  │ │  ■  │●●│ │ ┌─┐ ┌─┐  │ │  ■■■■■  │
│ ●─────  │ │  ■  │●●│ │ ┌─┐ ┌─┐  │ │  ─────  │
│ ●─────  │ │     │●●│ │ ┌─┐      │ │  ●  ●  │
│ ●─────  │ │     │  │ │         │ │         │
│  클래식  │ │  분할  │ │  카드   │ │ 하이라이트│
└──────────┘ └──────────┘ └──────────┘ └──────────┘
```

### 8-3. JavaScript 상태 변수

```javascript
let S = {
    file: null,
    cnt: 10,
    slides: null,
    out: null,
    preview_uid: null,
    design: {
        preset: "corporate",
        primary_color: null,
        accent_color: null,
        font_name: "Malgun Gothic",
        company_name: "",
        presenter_name: "",
        logo_uid: null,
        footer_text: "",
        slide_number: true,
        content_layout: "classic",
    }
};
```

### 8-4. 로고 업로드 즉시 처리

```javascript
logoFileInput.addEventListener("change", async (e) => {
    const file = e.target.files[0];
    if (!file) return;
    const fd = new FormData();
    fd.append("logo", file);
    const res = await fetch("/api/upload-logo", { method: "POST", body: fd });
    const d = await res.json();
    if (d.ok) {
        S.design.logo_uid = d.logo_uid;
        logoPreview.src = URL.createObjectURL(file);
        logoPreview.style.display = "block";
    }
});
```

### 8-5. 컬러 피커 양방향 동기화

```javascript
// hex input ↔ color input 동기화
primaryHexInput.addEventListener("input", () => {
    if (/^#[0-9A-Fa-f]{6}$/.test(primaryHexInput.value)) {
        primaryColorInput.value = primaryHexInput.value;
        S.design.primary_color = primaryHexInput.value;
    }
});
primaryColorInput.addEventListener("input", () => {
    primaryHexInput.value = primaryColorInput.value;
    S.design.primary_color = primaryColorInput.value;
});

// "초기화" 버튼 → null로 리셋 (preset 색상 사용)
primaryResetBtn.addEventListener("click", () => {
    S.design.primary_color = null;
    primaryHexInput.value = "";
    primaryColorInput.value = "#000000";
});
```

### 8-6. `/api/generate` 요청 수정

```javascript
const res = await fetch("/api/generate", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
        slides: S.slides,
        design: S.design,
        pdf_name: S.file.name,
    })
});
```

---

## 9. preview.html 변경 명세

### 9-1. design 정보를 slides JSON에서 로드

`/api/slides/<uid>` 응답에 `design` 필드가 포함되므로:

```javascript
const data = await res.json();
slides = data.slides || [];
design = data.design || { preset: "corporate" };

// Resolved 색상 팔레트를 JS에서도 동일하게 계산
const t = resolveTheme(design);
```

### 9-2. `resolveTheme(design)` JS 구현

`PRESETS`의 색상 정보를 JS 상수로도 정의 (Python과 동일한 값).

```javascript
const JS_PRESETS = {
    corporate: { header: "#1E3A5F", accent: "#4A90D9", confirm: "#1D9E75",
                 light: "#EBF2FA", bg: "#FFFFFF", text: "#1A2233",
                 title_sub: "#A8C8E8", title_dark: "#152B4A",
                 header_style: "full", bullet_style: "circle" },
    startup:   { header: "#0F172A", accent: "#6C63FF", ... },
    // ... 8종 전부
};

function resolveTheme(design) {
    const p = JS_PRESETS[design.preset] || JS_PRESETS.corporate;
    const t = { ...p };
    if (design.primary_color) { t.header = design.primary_color; t.title_dark = design.primary_color; }
    if (design.accent_color)  { t.accent = design.accent_color; t.confirm = design.accent_color; }
    t.content_layout = design.content_layout || "classic";
    t.font_name = design.font_name || "Malgun Gothic";
    t.company_name = design.company_name || "";
    t.presenter_name = design.presenter_name || "";
    t.footer_text = design.footer_text || "";
    t.slide_number = design.slide_number !== false;
    return t;
}
```

### 9-3. 렌더러 확장

`renderContent(data, t)` 함수를 `t.content_layout`에 따라 분기:

```javascript
function renderContent(data, t) {
    const layout = t.content_layout || "classic";
    if (layout === "split")     return renderContentSplit(data, t);
    if (layout === "card")      return renderContentCard(data, t);
    if (layout === "highlight") return renderContentHighlight(data, t);
    return renderContentClassic(data, t);
}
```

각 레이아웃의 HTML/CSS 렌더링은 Python 구현과 동일한 레이아웃으로 작성.

### 9-4. 푸터/번호 표시

슬라이드 인덱스 정보를 렌더링 시 전달:

```javascript
function goTo(i) {
    // ...
    document.getElementById("slideCanvas").innerHTML =
        renderSlide(slides[i], t, i + 1, slides.length);
}

function renderSlide(data, t, slideNum, total) {
    // renderContent/Title/Agenda/Summary에 slideNum 전달
}

// footer 렌더링 (content/agenda/summary에 추가)
function renderFooter(t, slideNum) {
    if (!t.footer_text && !t.slide_number) return "";
    return `
        <div style="position:absolute;bottom:0;left:0;right:0;height:34px;background:${t.light};display:flex;align-items:center;padding:0 20px">
            <div style="flex:1;font-size:9px;color:${t.accent}">${esc(t.footer_text)}</div>
            ${t.slide_number ? `<div style="font-size:9px;color:${t.text}">${slideNum}</div>` : ""}
        </div>`;
}
```

---

## 10. requirements.txt 변경

```
flask==3.0.3
anthropic==0.34.2
python-pptx==1.0.2
PyMuPDF==1.24.10
python-dotenv==1.0.1
Pillow>=10.0.0        ← 신규 추가 (로고 이미지 크기 파악용)
```

---

## 11. 파일 구조 최종

```
pdf-to-ppt/
├── app.py                      # 수정: /api/generate, /api/presets, /api/upload-logo, /api/fonts
├── core/
│   ├── claude_analyzer.py      # 변경 없음
│   ├── ppt_generator.py        # 대규모 수정: PRESETS, 4종 레이아웃, 브랜드 기능, 헬퍼 함수
│   ├── pdf_parser.py           # 변경 없음
│   └── history.py              # 변경 없음
├── templates/
│   ├── index.html              # 대규모 수정: 디자인 설정 패널 (탭 3개)
│   └── preview.html            # 수정: resolveTheme, 4종 레이아웃 렌더러, 푸터
├── uploads/                    # PDF 임시 + logo_{uid}.{ext} 저장
├── outputs/                    # .pptx + {uid}_slides.json (design 필드 포함)
└── requirements.txt            # Pillow 추가
```

---

## 12. 구현 순서 (권장)

```
1. requirements.txt에 Pillow 추가 후 pip install

2. ppt_generator.py
   a. PRESETS 딕셔너리 추가
   b. _hex_to_rgb, _resolve_theme 구현
   c. _add_logo, _add_footer, _render_header, _add_bullet 헬퍼 구현
   d. 기존 슬라이드 함수들 signature 변경 (+ slide_index 파라미터)
   e. _content_slide_split, _card, _highlight 구현
   f. generate_pptx 시그니처 및 내부 로직 변경

3. app.py
   a. /api/upload-logo 추가
   b. /api/presets 추가
   c. /api/generate의 design 파라미터 처리 + 하위 호환

4. index.html
   a. 디자인 설정 카드 HTML 구조 작성
   b. 탭 전환 JS
   c. 프리셋 그리드 동적 로딩 (/api/presets)
   d. 컬러 피커 양방향 동기화
   e. 로고 업로드 처리
   f. generate 요청 body 수정

5. preview.html
   a. JS_PRESETS 상수 추가
   b. resolveTheme 함수
   c. 4종 레이아웃 렌더러
   d. 푸터/번호 렌더링
```

---

## 13. 테스트 체크리스트

- [ ] 프리셋 8종 각각 PPT 생성 후 PowerPoint에서 열기
- [ ] primary_color/accent_color override가 색상에 정상 반영되는지
- [ ] 로고 PNG/JPG 업로드 후 슬라이드 우측 상단에 삽입되는지 (종횡비 유지)
- [ ] 회사명/발표자명이 타이틀 슬라이드 하단에 표시되는지
- [ ] 푸터 텍스트 + 슬라이드 번호가 모든 비-타이틀 슬라이드에 표시되는지
- [ ] content_layout 4종 생성 후 레이아웃이 맞는지
- [ ] 기존 `theme` 필드만 보내는 요청이 하위 호환되는지
- [ ] preview.html에서 4종 레이아웃이 Python과 동일하게 렌더링되는지
- [ ] 슬라이드 번호 OFF 시 번호가 숨겨지는지
