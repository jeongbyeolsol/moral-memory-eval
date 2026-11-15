# LLMKit 개발·참조 문서

`llmkit`은 OpenAI와 Gemini를 같은 Python 인터페이스로 호출하는 범용 클라이언트입니다. 연구의 문항·프로필·정답·trial 관리와 결과 분석은 호출하는 프로젝트가 담당합니다. 연구 실행 방법은 [루트 사용 안내](../../README.md), 연구 전용 구현은 [moral_memory_eval 문서](../moral_memory_eval/README.md)를 참고하세요.

모든 셸 명령과 예제 파일 경로는 프로젝트 루트 기준입니다. Python 코드 중 `LLMClient`를 실제 제공자로 생성해 호출하는 예제는 API를 사용합니다.

## 목차

- [1. 구성과 책임](#1-구성과-책임)
- [2. 설치와 공개 인터페이스](#2-설치와-공개-인터페이스)
- [3. 설정과 인증](#3-설정과-인증)
- [4. 호출 수명과 대화](#4-호출-수명과-대화)
- [5. 공통 스키마](#5-공통-스키마)
- [6. 구조화된 출력](#6-구조화된-출력)
- [7. 제공자 어댑터의 차이](#7-제공자-어댑터의-차이)
- [8. JSON·JSONL 입출력](#8-jsonjsonl-입출력)
- [9. 저장 형식 변경과 마이그레이션](#9-저장-형식-변경과-마이그레이션)
- [10. 오류 처리](#10-오류-처리)
- [11. 테스트 대역과 제공자 확장](#11-테스트-대역과-제공자-확장)
- [12. 예제와 검증](#12-예제와-검증)

## 1. 구성과 책임

| 파일 | 책임 |
| --- | --- |
| [__init__.py](__init__.py) | 클라이언트·설정·공통 모델·예외의 공개 import 경로 |
| [client.py](client.py) | 제공자 선택, `ask`·`generate`, 구조화된 응답 검증, 연결 종료 |
| [config.py](config.py) | 모델·HTTP 설정과 환경변수·API 키 해석 |
| [schemas.py](schemas.py) | 제공자에 독립적인 요청·응답 모델 |
| [errors.py](errors.py) | SDK와 구별되는 패키지 예외 |
| [io.py](io.py) | 버전이 있는 JSON·JSONL 검증, 마이그레이션, 저장 |
| [providers/__init__.py](providers/__init__.py) | 제공자와 테스트 대역이 구현하는 `Provider` Protocol |
| [providers/openai.py](providers/openai.py) | OpenAI Responses API 변환과 응답 정규화 |
| [providers/gemini.py](providers/gemini.py) | Gemini Developer API 변환과 응답 정규화 |

의존 방향은 호출 프로그램 → `LLMClient` → 제공자 어댑터 → 공식 SDK입니다. 외부 JSON 파일은 `io`를 통해 모델로 변환합니다. `llmkit` 내부는 CREAK, 도덕성 점수, 실험 파일 경로에 의존하지 않습니다.

현재 지원 범위는 동기 텍스트 대화와 Pydantic 기반 구조화된 출력입니다. 비동기·스트리밍·도구 호출·이미지 입력·실험 병렬화는 별도 인터페이스로 구현해야 합니다.

## 2. 설치와 공개 인터페이스

이 저장소에 설치하면 `llmkit`과 `moral_memory_eval`이 함께 설치됩니다.

```bash
python -m pip install -e '.[dev,analysis]'
```

다른 연구 저장소에서도 이 프로젝트 경로를 설치한 뒤 `from llmkit import ...`로 사용할 수 있습니다. 배포 프로젝트 이름은 `moral-memory-eval`, Python import 이름은 `llmkit`입니다.

주요 진입점은 다음과 같습니다.

```python
from llmkit import (
    ClientConfig,
    GenerationConfig,
    LLMClient,
    LLMRequest,
    LLMResponse,
    LLMResult,
    Message,
    TokenUsage,
)
from llmkit.io import append_jsonl, load_json, load_jsonl, save_json, save_jsonl
```

`SchemaModel`, `ProviderName`은 `llmkit.schemas`, `Provider`는 `llmkit.providers`에서 가져옵니다.

## 3. 설정과 인증

### ClientConfig

| 필드 | 타입·기본값 | 의미 |
| --- | --- | --- |
| `provider` | `"openai"` 또는 `"gemini"`, 필수 | 제공자 선택 |
| `model` | 비어 있지 않은 문자열, 필수 | 계정에서 사용할 수 있는 모델 ID |
| `timeout` | 양의 유한 실수, `60.0` | 개별 HTTP 요청 제한 시간(초) |
| `max_retries` | 0 이상 정수, `2` | 공식 SDK에 전달할 재시도 횟수 |

```python
from llmkit import ClientConfig

explicit = ClientConfig(provider="openai", model="YOUR_MODEL_ID", max_retries=0)
from_environment = ClientConfig.from_env("openai")
overridden = ClientConfig.from_env("openai", model="YOUR_OTHER_MODEL_ID")
```

`from_env`는 제공자별 `OPENAI_MODEL` 또는 `GEMINI_MODEL`을 읽습니다. 명시적 `model=`이 우선합니다. 선택된 값이 없거나 공백뿐이면 `ConfigurationError`이며 다른 모델로 대체하지 않습니다. 직접 `ClientConfig(...)`를 생성하면 모델 환경변수에 의존하지 않습니다. timeout·재시도는 환경변수에서 읽지 않습니다.

라이브러리는 `.env`를 자동으로 로드하지 않습니다. 필요하면 호출 프로그램이 먼저 명시적으로 준비합니다.

```python
from dotenv import load_dotenv

load_dotenv(".env", override=False)
```

### API 키 우선순위

`LLMClient(config, api_key="...")`에 전달한 값이 해당 환경변수보다 우선합니다. 환경변수는 `OPENAI_API_KEY` 또는 `GEMINI_API_KEY`입니다. 명시적 빈 키를 환경변수로 조용히 대체하지 않으며, 키가 누락되거나 공백뿐이면 `ConfigurationError`입니다.

키는 `ClientConfig`나 `LLMRequest`·`LLMResponse`에 저장하지 않습니다. 환경변수와 모델 선택은 서로 분리되어 있어 `OPENAI_MODEL`만 있어도 인증이 충족되는 것은 아닙니다.

## 4. 호출 수명과 대화

### 질문 하나 보내기

```python
from llmkit import ClientConfig, GenerationConfig, LLMClient

with LLMClient(ClientConfig.from_env("openai")) as client:
    response = client.ask(
        "관심사 분리를 한 문장으로 설명해 줘.",
        system="정확하고 간결하게 답변하세요.",
        generation=GenerationConfig(max_output_tokens=1024),
    )
    print(response.text)
    print(response.usage)
```

`ask(prompt, *, system=None, generation=None, response_model=None)`은 메시지를 만들어 `generate`에 위임합니다. `system=None`이면 system 메시지를 추가하지 않습니다.

컨텍스트 매니저는 종료 시 SDK HTTP 연결을 닫습니다. 직접 수명을 관리하면 `close()`를 호출합니다. `close()`는 반복 호출할 수 있지만 닫힌 클라이언트에서 요청하면 `RuntimeError`가 발생합니다. 주입한 테스트 제공자도 클라이언트를 닫으면 함께 닫힙니다.

### 대화 이력을 명시하기

```python
from llmkit import LLMRequest, Message

request = LLMRequest(
    messages=[
        Message(role="system", content="간결하게 답변하세요."),
        Message(role="user", content="JSON이 뭐야?"),
        Message(role="assistant", content="데이터를 표현하는 텍스트 형식입니다."),
        Message(role="user", content="JSONL과의 차이는?"),
    ]
)
# 열린 client에서 실행: response = client.generate(request)
```

클라이언트는 대화 이력을 내부에 누적하지 않습니다. 각 요청은 전달된 메시지만 사용합니다. 여러 독립 실험 trial을 같은 클라이언트로 호출해도 이전 trial의 대화가 자동으로 추가되지 않습니다.

## 5. 공통 스키마

공통 모델은 `SchemaModel`을 상속하여 `strict=True`, `extra="forbid"`, `frozen=True`를 사용합니다. 타입 변환과 알 수 없는 필드를 거부합니다. `frozen`은 속성 재할당을 제한하지만 내부 list까지 불변으로 만드는 것은 아니므로, 새 요청을 구성하는 방식으로 수정하세요.

### 요청 모델

| 모델 | 필드·검증 |
| --- | --- |
| `Message` | `role`: system/user/assistant, `content`: 길이 1 이상의 문자열 |
| `GenerationConfig` | `temperature`: 0~2 또는 None, `max_output_tokens`: 양의 정수 또는 None, `reasoning_effort`: 지원 문자열 또는 None |
| `LLMRequest` | 하나 이상의 `messages`, 기본 `generation=GenerationConfig()` |

System 메시지는 대화 메시지보다 앞에 있어야 하고 user 메시지가 하나 이상 필요합니다. 빈 메시지 목록, system만 있는 요청, 잘못된 역할, 필수 필드 누락은 Pydantic `ValidationError`입니다.

생성 옵션의 `None`은 API에 보내지 않습니다. 모델 기본값을 사용하며 미지원 옵션을 조용히 삭제하거나 바꾸지 않습니다. 모델이 특정 temperature·토큰 옵션을 지원하는지는 실제 API가 결정합니다.

### Reasoning effort

```python
from llmkit import GenerationConfig

generation = GenerationConfig(max_output_tokens=1024, reasoning_effort="medium")
```

`reasoning_effort`는 `none`, `low`, `medium`, `high`, `xhigh`, `max` 중 하나 또는 None입니다. 문자열 `"none"`은 추론 수준을 명시한 값이고 Python None은 옵션 미지정이므로 구별합니다. OpenAI 어댑터가 `reasoning={"effort": "medium"}`처럼 Responses API의 중첩 형식으로 변환합니다. `reasoning_effort`라는 최상위 API 인수를 보내지 않습니다. 일반·구조화된 호출 모두 같은 매핑을 사용합니다.

Gemini에는 이 OpenAI 옵션을 변환하거나 무시하지 않고 ConfigurationError를 발생시킵니다. 범용 클라이언트와 Gemini 어댑터 모두 호출 전에 검사하며, 실험 실행기는 요청 전체의 지원 여부를 결과 생성 전에 검사합니다. OpenAI의 개별 모델이 허용하는 수준은 API에서도 검증하므로 모든 모델이 여섯 값을 지원한다고 가정하지 않습니다.

이 필드는 미지정이면 모델 dump·JSON에서 생략합니다. 기존 temperature·max_output_tokens의 null 표현은 바꾸지 않으므로 기존 요청의 정규화 해시를 유지합니다. 중첩된 요청·준비 설정·결과 모델에도 같은 직렬화 규칙이 적용됩니다. 값이 명시되면 그대로 저장되어 실행과 Resume의 생성 설정 비교에 포함됩니다.

### 응답 모델

| 모델 | 필드 |
| --- | --- |
| `TokenUsage` | `input_tokens`, `output_tokens`, `total_tokens`: 0 이상 정수 또는 None |
| `LLMResponse` | 필수 `provider`, `model`, `text`; 선택 `response_id`, `usage`, `finish_reason` |
| `LLMResult` | `request: LLMRequest`, `response: LLMResponse` |

`response.model`은 어댑터가 정규화한 응답 모델 이름입니다. 요청한 모델 ID와 실제 반환 버전이 다를 수 있습니다. 제공자가 usage를 주지 않으면 `usage=None`, 일부 카운트를 주지 않으면 해당 카운트가 None입니다. 모르는 사용량을 0으로 만들거나 항상 입력+출력=전체라고 가정하지 않습니다.

Gemini 응답에 model_version이 없으면 요청한 모델 ID를 response.model에 사용합니다. 따라서 이 값이 항상 별도의 모델 snapshot을 증명하는 것은 아닙니다.

`LLMResponse`는 답변 문자열과 공통 메타데이터를 보존하며 SDK 응답 객체나 전체 raw HTTP JSON을 보존하지 않습니다. `LLMResult`에는 연구용 trial ID·정답·프로필이 없습니다. 연구 패키지는 별도의 결과 모델을 정의합니다.

## 6. 구조화된 출력

응답 형식은 호출자가 정의한 Pydantic 모델을 사용합니다.

```python
from llmkit import ClientConfig, LLMClient
from llmkit.schemas import SchemaModel


class Answer(SchemaModel):
    summary: str
    keywords: list[str]


with LLMClient(ClientConfig.from_env("openai")) as client:
    response = client.ask("Pydantic을 설명해 주세요.", response_model=Answer)
    answer = response.parse(Answer)
    print(answer.summary)
```

`generate(request, *, response_model=Answer)`도 같은 방식입니다. 클라이언트는 모델 타입을 어댑터에 전달하고, 반환된 `response.text`를 `model_validate_json(..., strict=True)`로 다시 검증합니다. 반환 타입은 항상 `LLMResponse`이고, `parse(Answer)`가 검증된 `Answer` 객체를 반환합니다.

`parse()`만 호출하면 로컬 검증만 수행합니다. 제공자에 출력 스키마도 전달하려면 요청 시 `response_model=`을 지정해야 합니다. JSON을 요구하는 프롬프트만 작성하는 것과는 다릅니다.

일반 `BaseModel`도 사용할 수 있지만 알 수 없는 필드 거부 여부는 그 모델의 설정에 달려 있습니다. 엄격한 계약이 필요하면 `SchemaModel` 또는 명시적 `ConfigDict(extra="forbid", strict=True)`를 사용하세요. 제공자·모델별 JSON Schema 지원 범위가 다르므로 단순한 필수 필드 객체부터 검증합니다.

잘못된 JSON·타입·필드·범위는 `StructuredOutputError`입니다. 패키지는 Markdown 제거, 필드 보완, 값 보정, 임의 기본 응답을 수행하지 않습니다.

## 7. 제공자 어댑터의 차이

| 항목 | OpenAI | Gemini |
| --- | --- | --- |
| SDK | `openai` | `google-genai` |
| API | Responses API | Gemini Developer API (`vertexai=False`) |
| 일반 호출 | `responses.create` | `models.generate_content` |
| 구조화된 출력 | `responses.parse(text_format=...)` | `response_schema`와 JSON MIME type |
| System | 입력 메시지로 전달 | 앞쪽 system 메시지를 빈 줄로 합쳐 `system_instruction`으로 전달 |
| Assistant 역할 | assistant | model로 변환 |
| timeout | 초 단위로 전달 | 밀리초로 변환하여 전달 |
| 재시도 | `max_retries` | 총 시도 수 `max_retries + 1` |

OpenAI 어댑터는 `store=False`를 전달합니다. 응답 status가 completed가 아니거나 거절·빈 텍스트가 있으면 오류입니다. Gemini는 차단된 프롬프트, 후보 누락, STOP이 아닌 종료, 빈 텍스트를 오류로 취급하며 thought로 표시된 part는 답변 텍스트에서 제외합니다.

`finish_reason`은 제공자별 상태를 문자열로 정규화한 값입니다. OpenAI와 Gemini 값이 동일한 열거형이라고 가정하지 마세요. API·전송 실패는 공통 예외로 감싸고 원래 SDK 예외를 원인으로 연결합니다. SDK별 구현 세부 사항은 이 디렉터리 밖으로 퍼뜨리지 않습니다.

## 8. JSON·JSONL 입출력

### 저장 형식

모든 레코드는 버전 봉투를 사용합니다. JSONL은 각 줄에 객체 하나입니다.

```json
{
  "schema_version": "1.0",
  "data": {
    "messages": [{"role": "user", "content": "안녕하세요."}],
    "generation": {"temperature": null, "max_output_tokens": 256}
  }
}
```

봉투의 `schema_version`은 저장 형식 버전입니다. `LLMRequest` 자체에 필드로 추가하지 않으며 제공자 API에도 보내지 않습니다. 저장 모델이 어떤 타입인지 파일에 자동 기록하지 않으므로 로더에 올바른 모델을 지정해야 합니다.

```python
from llmkit import LLMRequest, Message
from llmkit.io import load_json, load_jsonl, save_json, save_jsonl

request = LLMRequest(messages=[Message(role="user", content="안녕하세요.")])
save_json("outputs/example-request.json", request)
restored = load_json("outputs/example-request.json", LLMRequest)
save_jsonl("outputs/example-requests.jsonl", [request])
restored_many = load_jsonl("outputs/example-requests.jsonl", LLMRequest)
```

### 함수와 저장 보장

| 함수 | 반환·동작 |
| --- | --- |
| `load_json(path, Model, *, migrations=None)` | Model 객체 하나 |
| `load_jsonl(path, Model, *, migrations=None)` | 전체 파일을 검증한 뒤 `list[Model]` |
| `save_json(path, value)` | 검증한 모델을 JSON 봉투로 저장 |
| `save_jsonl(path, values)` | iterable 전체를 검증한 뒤 JSONL로 저장 |
| `append_jsonl(path, value)` | 검증한 레코드 하나를 추가; 파일당 단일 작성자 전제 |

`save_json`·`save_jsonl`은 부모 디렉터리를 만들고 같은 디렉터리의 임시 파일을 교체하는 방식으로 저장합니다. **이 범용 함수 자체는 기존 파일을 덮어쓸 수 있습니다.** 연구 패키지의 파일 보존 정책은 별도의 존재 검사·배타적 게시·잠금으로 구현합니다. 여러 파일을 한 트랜잭션으로 저장하는 기능도 이 함수 자체에는 없습니다.

저장 전에 다시 검증하여 생성 후 수정되었거나 `model_construct`로 검증을 우회한 모델의 잘못된 데이터도 거부합니다. JSON 검증을 통해 datetime 같은 JSON 표현을 지원합니다. JSONL 전체 로더는 메모리에 레코드 전체를 반환하며 스트리밍 로더가 아닙니다.

잘못된 JSON, 중복 JSON 키, 비정상 JSON 숫자, 버전 누락·잘못된 타입·미지원 버전, 모델 검증 실패는 `DataError`입니다. JSONL의 빈 줄도 오류이고, 파싱·검증 오류에는 파일 경로와 줄 번호가 포함됩니다. 원본 CREAK의 빈 줄 처리 예외는 연구용 로더에만 있습니다.

## 9. 저장 형식 변경과 마이그레이션

기본 지원 저장 버전은 `"1.0"`입니다. 과거 형식은 `migrations={"과거 버전": 변환 함수}`로 명시적으로 등록합니다. 변환 함수는 봉투 전체를 받아 현재 봉투 전체를 반환하며, 반환 결과를 현재 모델로 검증합니다.

```python
from typing import Any

from llmkit import LLMResponse
from llmkit.io import load_json


def migrate_v01(record: dict[str, Any]) -> dict[str, Any]:
    data = dict(record["data"])
    data["text"] = data.pop("answer")
    return {"schema_version": "1.0", "data": data}


# 0.1은 변환 작성법을 위한 예시이며 기본 지원 버전이 아닙니다.
# response = load_json(
#     "old-response.json", LLMResponse, migrations={"0.1": migrate_v01}
# )
```

변환은 자동 연쇄 실행하지 않습니다. 지원할 각 과거 버전을 현재 형식으로 직접 변환하는 함수를 등록합니다. 버전이 없는 파일을 구버전으로 추정하지 않으며 필수 필드가 없을 때 임의 값을 넣지 않습니다.

공통 모델을 변경할 때는 다음 순서로 확인합니다.

1. 연구 전용 필드라면 호출 프로젝트의 모델·변환 계층에 추가합니다. `LLMRequest`에 실험 메타데이터를 넣지 않습니다.
2. 공통 변경이 필요하면 `client.py`, 제공자 어댑터, 입출력, 예제, 연구 결과 모델에서 영향을 받는 인터페이스를 확인합니다.
3. 저장 형식 버전을 올릴 경우 `io.py`의 `SCHEMA_VERSION`과 `_Record.schema_version`의 허용 값을 함께 수정하고 구버전 변환 함수를 제공합니다.
4. 정상·필수 누락·타입 오류·추가 필드·저장 왕복·구버전 호환성 테스트를 갱신합니다.

## 10. 오류 처리

| 예외 | 의미 |
| --- | --- |
| `LLMKitError` | 패키지 오류의 상위 타입 |
| `ConfigurationError` | API 키 또는 환경변수 기반 모델 설정 누락·빈 값 |
| `ProviderError` | API·전송 실패; `provider`, `status_code`, `__cause__` 제공 |
| `ResponseError` | 거절·차단·미완료·빈 답변 |
| `StructuredOutputError` | `ResponseError` 하위 타입; 구조화된 출력 검증 실패 |
| `DataError` | 파일 입출력·저장 버전·데이터 검증 오류 |

Python 모델을 직접 잘못 생성하면 Pydantic `ValidationError`, 닫힌 클라이언트 사용은 `RuntimeError`입니다. HTTP 상태 코드가 없는 연결 오류 등의 `ProviderError.status_code`는 None일 수 있습니다.

```python
from llmkit import LLMKitError, ProviderError

# 실제 호출을 감싸는 예시:
# try:
#     response = client.generate(request)
# except ProviderError as exc:
#     print(exc.provider, exc.status_code)
# except LLMKitError as exc:
#     print(type(exc).__name__, str(exc))
```

재시도는 SDK 정책을 사용하며 범용 클라이언트가 별도 재시도를 중첩하지 않습니다. timeout은 전체 실험 시간이 아니고, `max_output_tokens`에는 모델에 따라 reasoning 토큰도 영향을 줄 수 있으므로 실제 모델에서 확인합니다.

## 11. 테스트 대역과 제공자 확장

외부 API 없이 클라이언트를 테스트하려면 `Provider` Protocol의 `generate`와 `close`를 구현해 주입합니다.

```python
from pydantic import BaseModel

from llmkit import ClientConfig, LLMClient, LLMRequest, LLMResponse


class FakeProvider:
    def generate(
        self,
        request: LLMRequest,
        *,
        response_model: type[BaseModel] | None = None,
    ) -> LLMResponse:
        return LLMResponse(provider="openai", model="mock", text="모의 답변")

    def close(self) -> None:
        pass


with LLMClient(ClientConfig(provider="openai", model="mock"), provider=FakeProvider()) as client:
    response = client.ask("테스트")
    assert response.text == "모의 답변"
```

테스트 제공자를 주입하면 SDK 클라이언트와 실제 API 키가 필요하지 않습니다. 어댑터 자체는 `sdk_client=`에 테스트용 SDK 클라이언트를 주입할 수도 있습니다. 테스트의 모의 HTTP 전송 계층은 실제 SDK의 요청 변환·응답 처리를 네트워크 없이 확인합니다.

제공자를 추가할 때는 `providers/` 안에 변환·호출·정규화를 구현하고, `ProviderName`, 키·모델 환경변수 매핑, `LLMClient`의 제공자 선택을 함께 확장합니다. SDK 구조를 공통 모델이나 연구 코드에 노출하지 않습니다. 현재는 고정된 두 제공자를 명시적으로 선택하며 자동 플러그인 등록 시스템은 없습니다.

## 12. 예제와 검증

```bash
# 실제 API 호출 예제: 사용할 키와 모델을 .env에 설정한 뒤 실행
python examples/simple_chat.py --provider openai --prompt "LLM이란 무엇인가요?"
python examples/file_chat.py --provider openai --input inputs/request.json

# 네트워크 없는 검증
python -m pytest -q tests/test_client.py tests/test_schemas.py tests/test_io.py tests/test_providers.py
ruff check .
mypy
```

`simple_chat.py`의 `--prompt`는 생략할 수 있습니다. `file_chat.py`는 기본 `inputs/requests.jsonl` 또는 `--input`의 JSON·JSONL을 읽고 `LLMResult`를 저장합니다. 기본 출력은 `outputs/chat-<고유 ID>.jsonl`이며 실험 manifest 매칭·`Verdict` 강제·Resume는 수행하지 않습니다. 연구에는 [전용 실행기](../moral_memory_eval/README.md)를 사용합니다.

## 라이선스

프로젝트 코드는 [MIT](../../LICENSE)입니다. CREAK 유래 내용의 원저작자·라이선스는 [THIRD_PARTY_NOTICES.md](../../THIRD_PARTY_NOTICES.md)와 [보존된 원문](../../third_party/CREAK-LICENSE.txt)을 따릅니다.
