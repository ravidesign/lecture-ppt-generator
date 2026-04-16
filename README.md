# 📚 Lecture. — PDF to PPT 강의 교안 생성기

## 설치

```bash
cd ~/Documents/pdf-to-ppt
pip3 install -r requirements.txt
cp .env.example .env
# .env 파일 열어서 ANTHROPIC_API_KEY 입력
```

## 실행

```bash
python3 app.py
# → http://localhost:5050
```

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
