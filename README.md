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

## 2. 문항 준비

동봉된 [검토 문항 60개](dataset/selected_data/curated_claims_bundle/curated_claims.jsonl)는 참·거짓 각 30개입니다. [선정 기록](dataset/selected_data/curated_claims_bundle/curation_review.json)은 후보 풀 120개에서 선택한 기준과 검토 한계를 보존합니다. 원본 CREAK를 내려받지 않고 이 파일로 다음 단계부터 사용할 수 있습니다.

```bash
python -m moral_memory_eval.cli verify-selection \
  --claims dataset/selected_data/curated_claims_bundle/curated_claims.jsonl
```

새 문항을 추출하려면 [데이터 출처와 원본 준비 방법](dataset/README.md)을 따라 `dataset/creak/dev.jsonl`을 준비한 뒤 실행합니다. `.json` 확장자의 JSONL도 지원합니다. 원본 위치는 로컬 디렉터리 또는 사용자가 관리하는 링크로 지정할 수 있으며 특정 컴퓨터 경로에 의존하지 않습니다.

```bash
# 새 예비 문항: 참 3개 + 거짓 3개
python -m moral_memory_eval.cli sample \
  --source dataset/creak/dev.jsonl --n-true 3 --n-false 3 --seed 42 \
  --output dataset/selected_data/new-pilot-claims.jsonl

# 새 본실험 문항: 참 15개 + 거짓 15개, 예비 문항 제외
python -m moral_memory_eval.cli sample \
  --source dataset/creak/dev.jsonl --n-true 15 --n-false 15 --seed 42 \
  --exclude-claims dataset/selected_data/new-pilot-claims.jsonl \
  --output dataset/selected_data/new-main-claims.jsonl
```

선정 문항과 대응 `.meta.json`을 함께 보관합니다. 기존 파일은 덮어쓰지 않으며, 선정 파일이 이미 있으면 다시 추출하지 않고 재사용합니다. 새로 선정한 문항의 중복·무결성·원본 해시는 다음처럼 확인할 수 있습니다.

```bash
python -m moral_memory_eval.cli verify-selection \
  --claims dataset/selected_data/new-main-claims.jsonl \
  --against dataset/selected_data/new-pilot-claims.jsonl \
  --source dataset/creak/dev.jsonl
```

## 3. 프로필 선택과 요청 생성

[configs/profiles.json](configs/profiles.json)에서 메모리를 관리합니다. 현재 샘플은 `candidate_0`, `candidate_5`, `no_profile`이며 본실험 조건을 확정한 것은 아닙니다. 사용할 프로필만 `--profile-ids`에 지정합니다. 메모리가 `null`이면 메모리 없는 통제 조건입니다.

```bash
python -m moral_memory_eval.cli prepare \
  --claims dataset/selected_data/curated_claims_bundle/curated_claims.jsonl \
  --profiles configs/profiles.json \
  --profile-ids candidate_0 candidate_5 no_profile \
  --repeats 2 --seed 42 \
  --output-dir inputs/generated/experiment-v1
```

문항 60개 × 프로필 3개 × 반복 2회이면 **360개 요청**을 생성합니다. 출력 디렉터리가 이미 있으면 새 이름을 지정합니다. 프로필·문항·프롬프트·생성 옵션을 바꿀 때도 새 디렉터리로 준비합니다.

현재 `prepare` CLI의 기본 출력 토큰 제한은 1024이며 `--max-output-tokens`로 바꿀 수 있습니다. `temperature`는 기본값을 강제하지 않고 필요할 때 `--temperature`로 지정합니다. 실행 단계에서 이 생성 설정을 덮어쓰지 않습니다.

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

### GPT-6 Luna의 reasoning effort 고정

아래는 동봉된 검토 문항으로 설정을 준비하는 예시입니다. 프로필·문항·반복 수는 연구 설계에 맞게 선택하세요.

새 준비 디렉터리에 `medium`을 기록합니다. 이 명령은 API를 호출하지 않습니다.

```bash
python -m moral_memory_eval.cli prepare \
  --claims dataset/selected_data/curated_claims_bundle/curated_claims.jsonl \
  --profiles configs/profiles.json \
  --profile-ids candidate_0 candidate_5 no_profile \
  --repeats 2 --seed 42 --max-output-tokens 1024 \
  --reasoning-effort medium \
  --output-dir inputs/generated/gpt6-luna-medium-check-v1
```

모델은 실행 시 `--provider openai --model gpt-6-luna`로 선택합니다. `prepare`는 모델 ID를 받지 않고 생성 옵션을 고정합니다. `--reasoning-effort`는 `none`, `low`, `medium`, `high`, `xhigh`, `max`를 지원하며 생략하면 기존 동작을 유지합니다. Gemini에는 이 옵션을 지정한 요청을 실행할 수 없습니다.

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

기존 비공개 저장소를 public으로 바꾸면 과거 커밋·브랜치·태그의 내용도 노출될 수 있습니다. 현재 파일의 경로 정리와 `.gitignore`는 과거 기록을 지우지 않습니다. 공개 전에는 과거 기록의 개인 경로·인증 정보도 별도로 확인해야 합니다.

## 개발과 상세 문서

```bash
python -m pytest -q
ruff check .
ruff format --check .
mypy
```

자동 테스트는 네트워크를 차단한 Mock 기반입니다. 범용 질문 예제는 [LLMKit 문서](src/llmkit/README.md), 실험 데이터 형식·확장·기존 실행기와의 차이는 [실험 패키지 문서](src/moral_memory_eval/README.md)를 참고하세요.

## 라이선스와 CREAK 출처

프로젝트 코드는 [MIT License](LICENSE)로 제공합니다. CREAK에서 가져온 문항·ID·라벨·예시에는 원저작자의 MIT 저작권·허가 고지를 별도로 보존합니다. [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)에 출처·논문·인용과 수정 범위를, [CREAK 라이선스 원문](third_party/CREAK-LICENSE.txt)에 upstream 고지를 담았습니다.

CREAK: *A Dataset for Commonsense Reasoning over Entity Knowledge*, Yasumasa Onoe, Michael J.Q. Zhang, Eunsol Choi, Greg Durrett, NeurIPS 2021 Datasets and Benchmarks Track. [공식 저장소](https://github.com/yasumasaonoe/creak) · [논문](https://arxiv.org/abs/2109.01653).

동봉 subset과 검토 기록은 이 프로젝트의 연구용 가공물이며 CREAK의 공식 릴리스나 저자 보증을 의미하지 않습니다. 배포 시 upstream 고지와 라이선스도 함께 보존하세요.
