# Teach-On Screen Map

## Main Flow

### MF-01 Home / Empty
- 목적: 처음 진입, 파일 업로드 유도
- 핵심 CTA: `PDF 업로드`
- 비활성 영역: 설정 카드 전체

### MF-02 Home / File Attached
- 목적: 생성 전 설정 조정
- 핵심 CTA: `분석 시작`
- 사용자 액션
  - 강의 목적 선택
  - 디자인 설정
  - 선택 파트 미리 확인
  - OCR 보정 선택
  - 추가 지시사항 입력
  - 시험지 옵션 설정

### MF-03 Page Plan Preview
- 목적: 선택 파트 검증
- 핵심 CTA: `분석 시작`

### MF-04 Analyze Running
- 목적: 대기 불안 감소
- 핵심 요소
  - 현재 단계
  - 에이전트 상태
  - 진행 문구

### MF-05 Analyze Completed Draft
- 목적: 초안 검토 후 generate로 이동

### MF-06 Generate Done
- 목적: 결과물 다운로드 / 미리보기 진입

## Preview Flow

### PV-01 Slide Edit
- 좌측: 썸네일
- 중앙: 슬라이드 미리보기
- 우측: 편집 패널

### PV-02 Question Tab
- 목적: 문제 세트 read-only 확인

### PV-03 Variant Selection
- 목적: 현재 슬라이드만 3안 비교

### PV-04 Image Candidate Apply
- 목적: 자동 선택된 이미지 교체
- 주의: 적용 버튼이 명확해야 함

### PV-05 Artifact State
- 목적: PPT / 문제지 / 정답지 다운로드 상태 확인

## Dashboard Flow

### DB-01 Overview
- 운영 수치 요약

### DB-02 Jobs Monitoring
- 실행 중 작업
- 최근 결과물
- agent trace

### DB-03 Agent Control Center
- 대상 uid / job 지정
- agent 선택
- instruction 입력
- 실행 결과 확인

### DB-04 Connector Management
- 외부 연동 관리

### DB-05 Security / Auth
- 관리자 로그인
- 토큰
- allowlist / rate limit 상태

### DB-06 Deprecated / Slack
- 추후 삭제 예정
- 디자인에서는 회색 처리 또는 archive 처리

## 삭제 예정 영역
- Slack Command Center
- 최근 Slack 활동
- Slack 설정 카드

## 화면 간 연결 규칙
- `완료 화면 → 미리보기 → 완료 화면`은 반드시 왕복 가능
- `미리보기 돌아가기`는 홈이 아니라 완료 화면으로
- `분석 중`에는 사용자가 현재 위치를 잃지 않도록 상태 유지

