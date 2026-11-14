# LLM Lab

OpenAI와 Gemini를 같은 인터페이스로 호출하는 Python 패키지 `llmkit`과 연구 실험 예제입니다. API 통신, 데이터 입출력, 실험 실행, 분석을 분리하여 다른 프로젝트에서도 패키지를 재사용할 수 있습니다. Python 3.10 이상이 필요합니다.

## 설치 및 첫 실행

프로젝트 루트에서 실행합니다.

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
```

`.env.example`을 참고하여 루트의 `.env`에 사용할 제공자의 키와 모델 ID를 입력합니다.

```dotenv
OPENAI_API_KEY=your-openai-api-key
OPENAI_MODEL=YOUR_OPENAI_MODEL_ID
GEMINI_API_KEY=your-gemini-api-key
GEMINI_MODEL=YOUR_GEMINI_MODEL_ID
```

예제·실험 실행 스크립트만 `.env`를 명시적으로 읽습니다. 라이브러리는 환경변수 또는 `api_key=`로 전달한 키를 사용하며, 키를 결과나 설정 모델에 저장하지 않습니다. 이미 설정된 환경변수는 `.env`보다 우선하고, 명시적 `api_key=`는 환경변수보다 우선합니다.

`YOUR_OPENAI_MODEL_ID`, `YOUR_GEMINI_MODEL_ID`는 계정에서 사용할 수 있는 실제 모델 ID로 교체합니다. 모델은 `--model` 옵션, 선택한 제공자의 `OPENAI_MODEL` 또는 `GEMINI_MODEL` 순서로 결정합니다. 둘 다 없거나 선택된 값이 비어 있으면 오류를 발생시킵니다.

```bash
python examples/file_chat.py --provider openai

python examples/file_chat.py --provider gemini --input inputs/request.json
```

이 명령은 실제 API를 호출합니다. 테스트 명령은 API 키나 외부 연결 없이 실행할 수 있습니다.

## 파일에서 질문 읽기

기본 실행은 `inputs/requests.jsonl`을 읽고 `outputs/chat-<고유 ID>.jsonl`에 요청과 답변을 함께 저장합니다. 기본 경로는 프로젝트 루트를 기준으로 하며, `--input`, `--output`으로 지정한 상대 경로는 현재 작업 디렉토리를 기준으로 합니다. 지정한 파일 하나를 처리합니다.

```bash
# JSONL: 각 줄에 독립된 요청 한 개
python examples/file_chat.py --provider openai --input inputs/requests.jsonl \
  --output outputs/results.jsonl

# JSON: 요청 한 개; 환경변수의 모델을 이번 실행에서만 변경
python examples/file_chat.py --provider gemini --input inputs/request.json \
  --model YOUR_OTHER_MODEL_ID
```

JSON 입력 형식은 다음과 같습니다. JSONL은 같은 객체를 한 줄에 하나씩 작성합니다. 여러 질문을 하나의 대화로 이어가려면 한 요청의 `messages`에 대화 이력을 넣습니다. JSONL의 각 요청 사이에는 대화 이력을 공유하지 않습니다.

```json
{
  "schema_version": "1.0",
  "data": {
    "messages": [
      {"role": "system", "content": "친절하고 정확하게 답변해 주세요."},
      {"role": "user", "content": "LLM을 한 문장으로 설명해 줘."}
    ],
    "generation": {"max_output_tokens": 1024}
  }
}
```

`generation`은 생략할 수 있습니다. 입력 전체를 API 호출 전에 검증하며 잘못된 데이터나 빈 파일을 거부합니다. 결과의 `data`에는 `request`와 `response`가 들어갑니다. `load_jsonl(path, LLMResult)`로 다시 읽을 수 있습니다. 기존 출력 파일을 덮어쓰지 않으며, 호출 중 실패해도 완료된 결과는 남습니다. 자동 이어 실행은 지원하지 않습니다.

파일 경로 선택과 반복 실행은 예제 실행 코드가 담당하고, `LLMClient`는 검증된 `LLMRequest`만 받습니다. 따라서 `inputs/`라는 디렉토리나 특정 실험의 파일 형식에 라이브러리가 의존하지 않습니다. 프로젝트별 외부 형식이 생기면 해당 프로젝트의 로더에서 `LLMRequest`로 변환하면 됩니다.

직접 질문을 입력하는 기존 예제도 사용할 수 있습니다. `--prompt`를 생략하면 기본 질문을 사용합니다.

```bash
python examples/simple_chat.py --provider openai --prompt "LLM이란 무엇인가요?"
```

## Python에서 사용하기

```python
from llmkit import ClientConfig, GenerationConfig, LLMClient

config = ClientConfig(provider="openai", model="YOUR_MODEL_ID")
with LLMClient(config) as client:
    response = client.ask(
        "관심사 분리를 간단히 설명해 줘.",
        system="정확하고 간결하게 답변하세요.",
        generation=GenerationConfig(max_output_tokens=1024),
    )
    print(response.text)
    print(response.usage)
```

Gemini를 쓰려면 `provider="gemini"`와 모델 ID를 변경합니다. 컨텍스트 매니저는 SDK의 HTTP 연결을 닫습니다. 직접 관리할 때는 `client.close()`를 호출합니다. 다른 저장소에서는 이 프로젝트 경로를 `pip install -e /path/to/llm-lab`로 설치하여 사용합니다.

환경변수에서 모델을 읽으려면 `ClientConfig.from_env("openai")`를 사용합니다. `ClientConfig.from_env("openai", model="YOUR_MODEL_ID")`로 명시한 모델이 우선합니다. 이 함수는 `.env` 파일을 읽지 않으므로 호출하는 프로그램이 필요에 따라 환경변수를 준비합니다. `ClientConfig(provider=..., model=...)`로 직접 생성하는 방식도 유지됩니다.

대화 이력이 필요하면 `LLMRequest`에 메시지를 명시적으로 전달합니다. 클라이언트는 내부에 대화 이력을 저장하지 않습니다.

```python
from llmkit import LLMRequest, Message

request = LLMRequest(
    messages=[
        Message(role="system", content="친절하게 설명하세요."),
        Message(role="user", content="JSON이 뭐야?"),
        Message(role="assistant", content="데이터를 표현하는 텍스트 형식입니다."),
        Message(role="user", content="JSONL과의 차이는?"),
    ]
)
# 열린 클라이언트에서 실행: response = client.generate(request)
```

공통 메시지 역할은 `system`, `user`, `assistant`입니다. System 메시지는 대화 앞에만 배치하고 user 메시지를 하나 이상 포함해야 합니다. Gemini 어댑터는 앞쪽 system 메시지를 하나의 지시문으로 합치고 assistant 역할을 SDK의 model 역할로 변환합니다.

## 구조화된 출력

응답 구조를 Pydantic 모델로 정의하고 `response_model=`에 전달합니다. 제공자에게 JSON 스키마를 전달하며 반환된 JSON도 로컬에서 엄격하게 검증합니다.

```python
from pydantic import BaseModel, ConfigDict
from llmkit import ClientConfig, LLMClient


class Answer(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    explanation: str
    keywords: list[str]


with LLMClient(ClientConfig(provider="gemini", model="YOUR_MODEL_ID")) as client:
    response = client.ask("Pydantic이란 무엇인가요?", response_model=Answer)
    answer = response.parse(Answer)
    print(answer.explanation)
```

구조화된 출력과 생성 옵션의 지원 범위는 모델마다 다릅니다. 공통 옵션은 `temperature`와 `max_output_tokens`이며, 지정하지 않은 값은 API에 보내지 않습니다. 미지원 옵션을 조용히 삭제하거나 다른 값으로 대체하지 않습니다. 두 제공자의 JSON 스키마 지원 범위가 다르므로 먼저 단순한 객체 모델과 필수 필드부터 사용하는 것이 좋습니다.

## 데이터 저장과 버전 관리

외부 JSON 필드 접근은 `llmkit.io`의 로더와 명시적 마이그레이션 함수에 모읍니다. 내부 코드는 검증된 Python 모델을 사용합니다.

```python
from llmkit import LLMResponse
from llmkit.io import load_json, save_json

# save_json("outputs/answer.json", response)
response = load_json("outputs/answer.json", LLMResponse)
print(response.text)
```

모든 저장 레코드는 다음 봉투 구조를 사용합니다. JSONL은 각 줄에 이 구조를 가진 JSON 객체 하나를 저장합니다.

```json
{
  "schema_version": "1.0",
  "data": {
    "provider": "openai",
    "model": "example-model",
    "text": "답변",
    "response_id": null,
    "usage": null,
    "finish_reason": null
  }
}
```

- `load_json(path, Model)` / `load_jsonl(path, Model)`: 전체 데이터를 읽고 검증합니다.
- `save_json(path, model)` / `save_jsonl(path, models)`: 검증 후 임시 파일을 교체하는 방식으로 저장합니다.
- `append_jsonl(path, model)`: 완료된 실험 결과를 한 건씩 추가합니다. 파일 하나당 단일 작성자를 전제로 합니다.

버전 누락, 미지원 버전, 잘못된 타입, 필수 필드 누락, 알 수 없는 필드, 중복 JSON 키, 비정상 JSON 숫자는 `DataError`가 됩니다. JSONL의 빈 줄도 오류이며, 오류에는 경로와 줄 번호가 표시됩니다. `None`인 토큰 사용량은 API에서 해당 정보를 주지 않았다는 뜻입니다.

과거 형식을 지원해야 할 때는 해당 데이터 모델의 변환 함수를 작성하여 로더에 전달합니다. 아래 `0.1`은 마이그레이션 작성법을 설명하는 예시 버전이며, 기본 지원 버전은 `1.0`입니다.

```python
from typing import Any
from llmkit import LLMResponse
from llmkit.io import load_json


def migrate_v01(record: dict[str, Any]) -> dict[str, Any]:
    # 예시: 과거 응답의 answer 필드를 현재 text로 변환
    data = dict(record["data"])
    data["text"] = data.pop("answer")
    return {"schema_version": "1.0", "data": data}


# response = load_json(
#     "old-response.json", LLMResponse, migrations={"0.1": migrate_v01}
# )
```

변환 결과도 현재 모델로 검증합니다. 여러 과거 버전은 각각 현재 형식으로 직접 변환하는 함수를 등록합니다. 실제 저장 필드의 의미나 구조를 바꿀 때는 버전을 올리고, 마이그레이션·호환성 테스트를 추가합니다. 내부 모델을 바꾸면 `LLMClient`, 제공자 어댑터, 입출력 모델, 실험 결과 모델, 분석 함수의 영향을 함께 확인합니다.

## 스키마 수정 및 적용

프로젝트별 데이터 모델은 `experiments/<name>/schemas.py`에 Pydantic으로 정의합니다. `extra="forbid"`, `strict=True`를 설정하고 필드의 이름·타입·필수 여부를 명시합니다. 여러 프로젝트에서 공통으로 사용하는 요청·응답 계약을 변경할 때는 `src/llmkit/schemas.py`를 수정합니다.

| 변경 대상 | 적용 방법 |
| --- | --- |
| 입력 데이터 | `load_json(path, MyInput)` 또는 `load_jsonl(path, MyInput)`로 검증하고 실행 코드에서 `LLMRequest`로 변환합니다. |
| LLM 답변 형식 | `client.generate(request, response_model=MyAnswer)`로 스키마를 전달하고 `response.parse(MyAnswer)`로 검증된 객체를 얻습니다. |
| 저장 결과 | 결과용 Pydantic 모델을 정의하고 `save_json` / `save_jsonl`에 전달합니다. 읽을 때도 같은 모델을 지정합니다. |

`examples/file_chat.py`의 입력 스키마는 `LLMRequest`로 고정되어 있습니다. 프로젝트별 필드를 추가했다면 해당 프로젝트의 로더·실행 코드에서 변환해야 하며, JSON 파일만 수정해서 임의의 스키마를 적용할 수는 없습니다.

기존 저장 형식을 변경할 때는 다음을 함께 처리합니다.

1. 버전을 올릴 경우 `llmkit.io`의 `SCHEMA_VERSION`과 `_Record.schema_version`의 허용 값을 함께 수정합니다. 현재 버전은 `1.0`이며, 파일의 버전 값만 바꾸면 미지원 버전 오류가 발생합니다.
2. 위의 마이그레이션 예시처럼 구버전 데이터를 현재 형식으로 변환하는 함수를 작성하고, 읽는 코드의 `migrations=`에 등록합니다. 누락된 필수값을 임의로 채우지 않습니다.
3. 변경된 필드를 사용하는 실행·분석 코드도 확인하고, 정상 입력·필수 필드 누락·잘못된 타입·구버전 호환성 테스트를 추가합니다. `python -m pytest -q`로 검증합니다.

## 오류와 재시도

호출자는 `LLMKitError`로 패키지 오류를 처리하거나 아래 오류를 개별적으로 처리할 수 있습니다.

| 오류 | 의미 |
| --- | --- |
| `ConfigurationError` | API 키 또는 모델 환경변수 누락·빈 값 |
| `ProviderError` | API/전송 오류. `provider`, `status_code`, 원본 예외 `__cause__` 제공 |
| `ResponseError` | 거절·차단·빈 응답·미완료 응답 |
| `StructuredOutputError` | JSON/응답 스키마 검증 실패. `ResponseError`의 하위 타입 |
| `DataError` | 데이터 읽기·쓰기·버전·검증 오류 |

Python 모델 생성 시 잘못된 입력은 Pydantic `ValidationError`입니다. HTTP 오류는 제공자 SDK의 정책에 따라 재시도하며 `ClientConfig(timeout=60.0, max_retries=2)`로 조절합니다. 재시도를 겹쳐 구현하지 않습니다. `timeout`은 개별 HTTP 요청의 제한 시간(초)이며 전체 실험의 제한 시간이 아닙니다.

## Epistemics 예제

샘플 실험은 두 프로필 조건과 두 사실 명제를 조합하여 네 번 호출하고, `is_true`와 `reasoning`을 구조화된 출력으로 받습니다. 샘플 데이터는 실행 흐름을 설명하기 위한 예시입니다.

```bash
python -m experiments.epistemics.run --provider openai \
  --output outputs/epistemics-run1.jsonl

python -m experiments.epistemics.analyze outputs/epistemics-run1.jsonl \
  --output outputs/epistemics-summary.json
```

실행 결과에는 실행 ID, 프로필, 정답 명제, 요청 메시지와 생성 설정, 응답, 판정을 함께 저장합니다. 프로필·명제 ID 중복을 거부하고, 기존 결과 파일이 있으면 API를 호출하기 전에 중단합니다. 각 성공 결과를 즉시 저장하므로 중간 실패 시 앞선 결과가 남습니다. 자동 이어 실행은 제공하지 않으며, 일부만 완료된 파일도 분석할 수 있습니다. 분석은 API 없이 프로필별 정확도를 계산합니다.

다른 연구에서는 `experiments/<name>/`에 별도 스키마·실행·분석 코드를 추가하고 `llmkit`의 공개 인터페이스를 사용합니다.

## 구조

```text
src/llmkit/
  __init__.py           공개 인터페이스
  client.py             공통 클라이언트와 구조화된 출력 검증
  config.py             제공자·모델·HTTP 설정, 키 조회
  schemas.py            요청·응답·메시지·생성 설정
  errors.py             공통 예외
  io.py                 버전이 있는 JSON/JSONL 검증·변환·저장
  providers/
    __init__.py         테스트 대역 주입도 가능한 최소 Protocol
    openai.py           OpenAI Responses API 어댑터
    gemini.py           Gemini Developer API 어댑터
examples/simple_chat.py
examples/file_chat.py   JSON/JSONL 파일 입력 실행
inputs/                범용 요청 샘플 (경로 변경 가능)
experiments/epistemics/  실험별 스키마·데이터·실행·분석
tests/                  네트워크를 차단한 자동 테스트
```

현재 범위는 동기 텍스트 대화와 구조화된 출력입니다. 비동기 호출, 스트리밍, 도구 호출, 이미지 입력, 병렬 실험 실행은 필요할 때 별도 인터페이스로 확장합니다.

## 개발 및 검증

```bash
python -m pytest -q
ruff check .
ruff format --check .
mypy
```

모델 검증, JSON/JSONL 왕복, 구버전 변환, 데이터 오류, 파일 입력 실행, 모델 환경변수와 명시적 옵션 우선순위, 제공자별 메시지·옵션 변환, 토큰 사용량, 구조화된 출력, HTTP 오류, 차단·거절·잘린 답변, 실험 실행부터 분석까지 테스트합니다. 실제 SDK와 모의 HTTP 전송 계층을 사용하며 테스트 중 네트워크 연결을 차단합니다.

구현 참고: [OpenAI Responses API](https://developers.openai.com/api/reference/python/resources/responses/methods/create), [Google Gen AI Python SDK](https://googleapis.github.io/python-genai/).
