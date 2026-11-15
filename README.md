# Moral Memory Evaluation

사용자 메모리에 담긴 도덕적 평판이 LLM의 사실 판단과 자기보고 확신도에 미치는 영향을 평가합니다. **문항 선정 → 프로필과 요청 생성 → API 실행 → 결과 분석** 순서로 사용합니다.

| 문서 | 내용 |
| --- | --- |
| [LLMKit 상세 문서](src/llmkit/README.md) | 범용 클라이언트 사용법, 요청·응답 스키마, 제공자 어댑터, JSON 입출력, 확장 방법 |
| [실험 패키지 상세 문서](src/moral_memory_eval/README.md) | 데이터·manifest 구조, CLI 전체 옵션, 해시·trial ID 규칙, 실행·Resume·분석과 스키마 변경 |

아래 명령은 프로젝트 루트에서 실행합니다. 데이터 준비·검증·분석에는 API 키가 필요하지 않습니다. `run`은 `--dry-run`을 지정한 경우를 제외하고 실제 API를 호출합니다.

## 1. 설치와 환경 설정

Python 3.10 이상에서 설치합니다. 현재 실행기의 파일 잠금은 POSIX 환경을 사용합니다.

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev,analysis]'
```

[.env.example](.env.example)을 참고해 루트 `.env`에 사용할 제공자의 키와 접근 가능한 모델 ID를 입력합니다.

```dotenv
OPENAI_API_KEY=your-key
OPENAI_MODEL=YOUR_MODEL_ID
GEMINI_API_KEY=
GEMINI_MODEL=
```

모델은 `--model`이 환경변수보다 우선합니다. 이미 설정된 환경변수는 `.env`보다 우선합니다. Gemini를 사용할 때는 해당 키·모델을 설정하고 `--provider gemini`를 지정합니다.

## 2. 문항 선정

원본은 `dataset/creak/`의 외부 심볼릭 링크를 통해 읽습니다. 로컬 원본 파일명은 `dev.jsonl`입니다. 확장자가 `.json`인 CREAK JSONL도 지원합니다.

선정 파일이 이미 있다면 다시 추출하지 않고 다음 검증 단계부터 사용합니다. 아래 명령은 **새 선정 파일을 만들 때** 사용하는 예시이며, 기존 파일이 있으면 중단합니다. 다른 문항을 선정하려면 새 파일명을 지정하세요.

```bash
# 예비: 참 3개 + 거짓 3개
python -m moral_memory_eval.cli sample \
  --source dataset/creak/dev.jsonl --n-true 3 --n-false 3 --seed 42 \
  --output dataset/selected_data/pilot_claims.jsonl

# 본실험: 참 15개 + 거짓 15개, 예비 문항 제외
python -m moral_memory_eval.cli sample \
  --source dataset/creak/dev.jsonl --n-true 15 --n-false 15 --seed 42 \
  --exclude-claims dataset/selected_data/pilot_claims.jsonl \
  --output dataset/selected_data/main_claims.jsonl
```

선정 문항과 같은 이름의 `.meta.json`이 함께 저장됩니다. 두 파일을 함께 보관하고 문항의 적절성은 실험 전에 검토합니다.

```bash
python -m moral_memory_eval.cli verify-selection \
  --claims dataset/selected_data/main_claims.jsonl \
  --against dataset/selected_data/pilot_claims.jsonl \
  --source dataset/creak/dev.jsonl
```

## 3. 프로필 선택과 요청 생성

[configs/profiles.json](configs/profiles.json)에서 메모리를 관리합니다. 현재 샘플은 `candidate_0`, `candidate_5`, `no_profile`이며 본실험 조건을 확정한 것은 아닙니다. 사용할 프로필만 `--profile-ids`에 지정합니다. 메모리가 `null`이면 메모리 없는 통제 조건입니다.

```bash
python -m moral_memory_eval.cli prepare \
  --claims dataset/selected_data/main_claims.jsonl \
  --profiles configs/profiles.json \
  --profile-ids candidate_0 candidate_5 no_profile \
  --repeats 2 --seed 42 \
  --output-dir inputs/generated/experiment-v1
```

문항 30개 × 프로필 3개 × 반복 2회이면 **180개 요청**을 생성합니다. 출력 디렉터리가 이미 있으면 새 이름을 지정합니다. 프로필·문항·프롬프트·생성 옵션을 바꿀 때도 새 디렉터리로 준비합니다.

기본 출력 토큰 제한은 256이며 `--max-output-tokens`로 바꿀 수 있습니다. `temperature`는 기본값을 강제하지 않고 필요할 때 `--temperature`로 지정합니다. 실행 단계에서 이 생성 설정을 덮어쓰지 않습니다.

```text
inputs/generated/experiment-v1/
├── requests.jsonl       실제 LLM 요청
├── manifest.jsonl       문항·프로필·정답·trial 대응 정보
└── preparation.json    설정 스냅샷과 파일 해시
```

```bash
python -m moral_memory_eval.cli verify-prepared \
  --input-dir inputs/generated/experiment-v1
```

## 4. 실행과 이어 실행

먼저 API 호출 없이 검증합니다. 이 명령은 모델·키가 없어도 실행되며 결과 파일을 만들지 않습니다.

```bash
python -m moral_memory_eval.cli run \
  --input-dir inputs/generated/experiment-v1 --provider openai \
  --output outputs/experiment-run1.jsonl --dry-run
```

다음 명령은 **실제 API를 호출**합니다. 우선 성공 trial 2개까지만 실행하고, SDK 자동 재시도는 끕니다.

```bash
python -m moral_memory_eval.cli run \
  --input-dir inputs/generated/experiment-v1 --provider openai \
  --output outputs/experiment-run1.jsonl --max-calls 2 --max-retries 0
```

같은 준비 데이터와 모델·timeout·재시도 설정으로 이어 실행합니다. 아래 명령은 아직 완료되지 않은 trial **전체**를 실행합니다. 일부만 이어 실행하려면 `--max-calls`도 추가합니다.

```bash
python -m moral_memory_eval.cli run \
  --input-dir inputs/generated/experiment-v1 --provider openai \
  --output outputs/experiment-run1.jsonl --resume --max-retries 0
```

`--max-calls`는 새로 저장할 성공 trial 수의 제한입니다. HTTP 호출 수는 SDK 재시도에 따라 달라질 수 있습니다. 이미 완료된 trial은 건너뛰고, 기존 파일에 새 실행을 시작하려면 오류가 발생합니다.

```text
outputs/experiment-run1.jsonl       성공 결과
outputs/experiment-run1.run.json    예정 trial 전체와 실행 설정
outputs/experiment-run1.jsonl.lock  동시 작성 방지 잠금
```

결과와 `.run.json`을 함께 보관하세요. 손상된 결과는 자동 복구하지 않습니다. 서버 응답 후 로컬 저장 전에 종료된 경우까지 중복 호출 방지를 보장하지는 않습니다.

## 5. 분석

```bash
python -m moral_memory_eval.cli analyze \
  --results outputs/experiment-run1.jsonl \
  --output outputs/experiment-run1-summary.json
```

전체·프로필별 Accuracy, Agreement Rate, False-claim Agreement Rate, Mean Confidence, Brier Score를 계산합니다. `confidence`는 **자신의 진위 판단이 옳을 확률**이며, 명제가 참일 확률이 아닙니다.

부분 결과도 분석할 수 있습니다. `complete`와 `pending_trial_ids`로 남은 trial을 확인합니다. 분석 출력 파일도 기존 파일을 덮어쓰지 않으므로 새 경로를 사용합니다.

## 파일 보관과 문제 해결

원본 CREAK는 수정하지 않습니다. `dataset/selected_data/`와 `configs/profiles.json`은 Git으로 추적할 수 있고, 외부 원본 링크·`inputs/generated/`·`outputs/`·`.env`는 제외됩니다. Git 추가·커밋·push는 직접 결정하며, push 전의 로컬 데이터는 원격 백업된 상태가 아닙니다.

| 상황 | 처리 방법 |
| --- | --- |
| `Output already exists` | 기존 파일을 재사용하거나 새 출력 이름을 지정합니다. 실행 결과를 이어 쓸 때는 `--resume`을 사용합니다. |
| 모델·키 누락 | `.env`와 환경변수를 확인합니다. 모델은 `--model`로도 지정할 수 있습니다. |
| SHA-256·manifest·결과 불일치 | 대응 파일들을 함께 보관했는지 확인합니다. 파일을 임의로 고쳐 검증을 우회하지 않습니다. |
| 구조화된 응답·토큰 제한 오류 | 실패 trial을 확인하고 모델 지원 범위를 점검합니다. 생성 옵션 변경은 새 `prepare`로 적용합니다. |

## 개발과 상세 문서

```bash
python -m pytest -q
ruff check .
ruff format --check .
mypy
```

자동 테스트는 네트워크를 차단한 Mock 기반입니다. 범용 질문 예제는 [LLMKit 문서](src/llmkit/README.md), 실험 데이터 형식·확장·기존 실행기와의 차이는 [실험 패키지 문서](src/moral_memory_eval/README.md)를 참고하세요. 이전 템플릿 문서는 [_mdfiles/README.md](_mdfiles/README.md)에 보존되어 있습니다.
