# Teach-On Design Inventory

## 핵심 제품 영역
1. 생성 시작
2. 분석 진행
3. 슬라이드/문제 편집
4. 결과물 다운로드
5. 운영 대시보드

## 1. 생성 시작 화면
템플릿: [templates/index.html](/Users/joohyung/Documents/pdf-to-ppt/templates/index.html:1)

필수 블록
- 앱 타이틀
- 파일 업로드
- 강의 목적
- 디자인 설정
- 선택 파트 미리 확인
- OCR 옵션
- 추가 지시사항
- 시험지 옵션
- 분석 시작 버튼

상태
- Empty
- File attached
- Disabled before upload
- Preview loaded
- Analyze loading
- Error

## 2. 선택 파트 미리 확인
목적
- 사용자가 `신경계만 사용` 같은 요청이 실제로 어떤 페이지를 의미하는지 검증

필수 요소
- 범위 배지
- 선택 페이지 수
- 미리보기 heading list
- 안내 문구

## 3. 분석 진행
필수 요소
- stage 메시지
- 진행 상태
- 에이전트 상태 trace
- 재작업 발생 표시

## 4. 미리보기 / 편집
템플릿: [templates/preview.html](/Users/joohyung/Documents/pdf-to-ppt/templates/preview.html:1)

필수 블록
- 좌측 슬라이드 썸네일 목록
- 중앙 슬라이드 캔버스
- 우측 편집 패널
- 다운로드명
- 돌아가기
- 다운로드 버튼

세부 기능
- 슬라이드 제목/부제/포인트 수정
- 레이아웃 선택
- 발표자 노트
- 시안 3개 생성
- 이미지 후보 적용
- 문제지 탭

상태
- Slide edit
- Question preview
- Variant compare
- Image candidate apply
- Artifact available

## 5. 완료 화면
필수 블록
- 성공 메시지
- 다운로드 파일명
- 결과 요약 카드
- PPT / 문제지 / 정답지 다운로드
- 새 파일 만들기
- 슬라이드 미리보기 진입

## 6. 운영 대시보드
템플릿: [templates/dashboard.html](/Users/joohyung/Documents/pdf-to-ppt/templates/dashboard.html:1)

핵심 섹션
- 운영 개요
- 보안 / 운영 설정
- 작업 모니터링
- 최근 결과물
- Agent Control Center
- 커넥터 관리

주의
- Slack Command Center는 제거 예정
- 디자인 파일에서는 deprecated 영역으로만 유지

## 7. 시험지 영역
핵심 기능
- 문제 수
- 난이도 비율
- A/B 셔플
- 기관명 / 날짜 / 제한시간
- 문제지/정답지 다운로드

## 디자인 우선 개선 포인트
- 이미지 사용 슬라이드는 이미지 중심 레이아웃 우선
- 과밀 슬라이드 자동 분할은 최소화
- sparse slide는 한 장에서 해결
- 챕터 슬라이드는 내용 욕심 없이 간결하게

