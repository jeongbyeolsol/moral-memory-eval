# LLM Lab

LLM API 호출과 응답 처리를 위한 범용 Python 프로젝트.

다양한 LLM 제공자의 API를 통일된 인터페이스로 호출하고, 이를 여러 연구 및 실험 프로젝트에서 재사용하는 것을 목표로 한다.

## Project Structure

```text
llm-lab/
├── src/
│   └── llmkit/                 # 범용 LLM 패키지
│       ├── __init__.py
│       ├── client.py           # LLM 호출 인터페이스
│       ├── schemas.py          # 요청 및 응답 자료형
│       ├── config.py           # 모델 및 생성 설정
│       └── providers/          # API 제공자별 구현
│           ├── __init__.py
│           └── openai.py
│
├── examples/
│   └── simple_chat.py          # 기본 API 호출 예시
│
├── experiments/
│   └── epistemics/
│       ├── run.py              # 실험 실행
│       ├── analyze.py          # 실험 결과 분석
│       ├── profiles.json       # 사용자 프로필 조건
│       └── claims.jsonl        # 평가용 사실 명제
│
├── tests/                      # 테스트 코드
├── outputs/                    # API 응답 및 실험 결과
├── pyproject.toml              # Python 프로젝트 설정
├── .env                        # API 키 및 환경변수
├── .gitignore
└── README.md
```

## Architecture

프로젝트는 두 영역으로 구분한다.

### 1. LLMKit (`src/llmkit/`)

LLM과의 통신을 담당하는 범용 패키지.

- 모델 및 API 제공자 선택
- System/User 메시지 전달
- API 호출 및 응답 수신
- 모델 설정 및 응답 메타데이터 관리
- 오류 처리 및 구조화된 출력 지원

### 2. Experiments (`experiments/`)

LLMKit을 활용하는 개별 연구 프로젝트.

- 실험 데이터 및 조건 관리
- 반복 API 호출
- 결과 저장 및 분석

실험별 로직은 LLMKit 내부에 작성하지 않는다.

## Development Roadmap

1. 단일 LLM API 호출 및 응답 출력
2. 범용 `LLMClient` 인터페이스 구현
3. JSON 출력, 오류 처리 및 결과 저장 기능 추가
4. Epistemics 실험 연결
5. 필요에 따라 다른 LLM 제공자 지원

## Design Principle

**Separate LLM communication from experiment logic.**

LLMKit은 모델과 통신하는 방법을 제공하고, 각 실험은 모델에 무엇을 질문하고 어떻게 평가할지를 결정한다.