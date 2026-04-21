# Teach-On Figma Layer Naming System

## 목표
레이어 이름만 보고도 역할과 위치를 바로 파악할 수 있게 한다.

## 기본 규칙
- 공백 대신 하이픈 `-` 사용
- 한국어 대신 영문 명명 사용
- 같은 역할은 같은 prefix 사용
- 임시 레이어명 `Rectangle 1`, `Frame 23`, `Group` 금지

## 명명 포맷
`[PageCode]/[Section]/[Type]/[Name]`

예시
- `MF01/Header/Text/AppTitle`
- `MF01/Upload/Card/Dropzone`
- `PV03/RightPanel/Button/GenerateVariants`
- `DB02/Jobs/Card/AnalyzeJobItem`

## Prefix 표준
- `Page`: `MF`, `PV`, `DB`, `EX`, `FD`, `CP`
- `Section`: `Header`, `Hero`, `Control`, `Sidebar`, `Content`, `Footer`, `Modal`
- `Type`: `Frame`, `Group`, `Card`, `Button`, `Input`, `Text`, `Icon`, `Badge`, `List`, `Item`

## Auto Layout 프레임 규칙
- 최상위 화면 프레임: `PageCode/Canvas/Frame/Root`
- 큰 섹션 프레임: `PageCode/Content/Frame/SectionName`
- 리스트 컨테이너: `PageCode/Content/List/Name`
- 반복 아이템: `PageCode/Content/Item/Name`

## 컴포넌트 규칙
- Component set: `Cmp/[Category]/[Name]`
- Variant: `State=Default`, `State=Hover`, `State=Disabled`
- Size variant: `Size=SM`, `Size=MD`, `Size=LG`

예시
- `Cmp/Button/Primary`
- `Cmp/Input/TextField`
- `Cmp/Card/DownloadArtifact`
- `Cmp/Badge/Status`

## 텍스트 레이어 규칙
- `Text/Heading/H1`
- `Text/Heading/H2`
- `Text/Body/MD`
- `Text/Label/SM`
- 실제 화면에서는 접두사 없이 맥락 포함

예시
- `MF06/Hero/Text/SuccessTitle`
- `PV01/RightPanel/Text/SectionTitle`

## 아이콘 / 이미지 규칙
- `Icon/Arrow/Left`
- `Icon/Action/Download`
- `Image/Preview/SlideThumb`
- `Image/Illustration/UploadEmpty`

## 상태 케이스 suffix
- `--default`
- `--hover`
- `--active`
- `--disabled`
- `--error`
- `--success`
- `--loading`

예시
- `Cmp/Button/Primary--disabled`
- `MF03/PagePlan/Card/Selected--active`

## 제거 예정 영역
- Slack 관련 레이어는 `Deprecated/Slack/...` 으로 이동
- 최종 정리 시 삭제 우선순위 1순위

