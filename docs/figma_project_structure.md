# Teach-On Figma Project Structure

## 목적
Teach-On의 현재 웹 앱 구조를 Figma에서 바로 재구성할 수 있도록 파일, 페이지, 섹션, 프레임 체계를 표준화한다.

## 파일명
`Teach-On Product Design System`

## 최상위 페이지 구조
1. `00 Cover`
2. `01 Foundations`
3. `02 Components`
4. `03 Main Flow`
5. `04 Preview Flow`
6. `05 Dashboard`
7. `06 Exam Flow`
8. `07 Deprecated`
9. `99 Archive`

## 페이지별 역할

### `00 Cover`
- 파일 소개
- 최신 버전 정보
- 작업 규칙
- 담당자 메모

### `01 Foundations`
- Color tokens
- Typography scale
- Spacing scale
- Radius / shadow / stroke
- Grid system
- Icon usage
- Motion guideline

### `02 Components`
- Top navigation
- Buttons
- Inputs / selects / textareas
- Upload dropzone
- Cards
- Tabs
- Status badges
- Progress / step indicators
- Modals
- Toast / inline feedback
- Download cards
- Agent status chips

### `03 Main Flow`
- `MF-01 Home / Empty`
- `MF-02 Home / File Attached`
- `MF-03 Page Plan Preview`
- `MF-04 Analyze Running`
- `MF-05 Analyze Completed Draft`
- `MF-06 Generate Done`

### `04 Preview Flow`
- `PV-01 Preview / Slide Edit`
- `PV-02 Preview / Question Tab`
- `PV-03 Preview / Variant Selection`
- `PV-04 Preview / Image Candidate Apply`
- `PV-05 Preview / Artifact Download State`

### `05 Dashboard`
- `DB-01 Overview`
- `DB-02 Jobs Monitoring`
- `DB-03 Agent Control Center`
- `DB-04 Connector Management`
- `DB-05 Security / Auth`

### `06 Exam Flow`
- `EX-01 Exam Options on Main`
- `EX-02 Question Preview`
- `EX-03 Exam Artifact Done`

### `07 Deprecated`
- Slack 관련 화면과 패널
- 삭제 예정 UI
- 실험용 구조

### `99 Archive`
- 이전 버전 시안
- 더 이상 사용하지 않는 레이아웃

## 메인 프레임 사이즈
- Desktop primary: `1440 x 1600`
- Desktop wide dashboard: `1600 x 1400`
- Tablet reference: `1024 x 1366`
- Mobile reference: `390 x 844`

## 공통 섹션 구성 규칙
- 페이지마다 `Header / Content / Footer Notes` 3구역으로 나눈다.
- 실제 구현 화면은 `Left aligned content + centered main canvas`를 기본으로 한다.
- 대시보드는 `dark console theme`, 메인 생성/완료 화면은 `light product theme`로 분리한다.

## Slack 처리 방침
- Slack 관련 UI는 현재 코드에 남아 있어도 디자인 체계에서는 `07 Deprecated`로 분리한다.
- 새 디자인 QA 범위에는 Slack 패널을 포함하지 않는다.
- 대시보드 최종 정보구조는 Slack 제거 이후에도 성립해야 한다.

## Figma에서 우선 그릴 순서
1. `01 Foundations`
2. `02 Components`
3. `03 Main Flow`
4. `04 Preview Flow`
5. `05 Dashboard`
6. `06 Exam Flow`
7. `07 Deprecated`

