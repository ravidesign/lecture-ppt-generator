# Teach-On Figma Build Sequence

## Step 1. Foundations 먼저 생성
- 색상 토큰
- 타이포 스케일
- spacing / radius / shadow
- light theme / dark theme 분리

## Step 2. Components 제작
- Button
- Input / Select / Textarea
- Upload card
- Status badge
- Progress / agent chip
- Download artifact card
- Sidebar thumbnail item
- Right edit panel section

## Step 3. Main Flow 제작
- `MF-01`부터 `MF-06`까지 순서대로
- Empty, Disabled, Loading, Success 상태 모두 포함

## Step 4. Preview Flow 제작
- 좌측 썸네일 / 중앙 캔버스 / 우측 패널 구조를 컴포넌트화
- 이미지 후보 적용, 시안 선택, 문제지 탭 상태 추가

## Step 5. Dashboard 제작
- Main product와 다른 visual language 유지
- 운영용 dark console 스타일 유지
- Slack 섹션은 `Deprecated` 표시

## Step 6. Exam Flow 제작
- 시험 옵션
- 문제지 결과 카드
- 정답지 결과 카드

## Figma 페이지 정리 기준
- 페이지별로 `Ready`, `In Progress`, `Deprecated` 라벨 부여
- 최종 승인본만 `03 Main Flow`, `04 Preview Flow`, `05 Dashboard`에 유지
- 시안은 `99 Archive`로 이동

## 레이어 QA 체크리스트
- `Frame 1`, `Group`, `Rectangle 12` 같은 이름 제거
- Auto layout 누락 없는지 확인
- Variant property 이름 통일
- 이미지/아이콘 레이어 이름 표준화
- Deprecated 영역 명시

## 현재 MCP 한계
- 지금 세션에서는 Figma 쓰기 권한이 없어 실제 파일 생성/레이어 수정은 못 함
- 이 문서 세트를 그대로 들고 쓰기 가능한 Figma MCP가 연결되면 바로 실작업으로 옮길 수 있음
