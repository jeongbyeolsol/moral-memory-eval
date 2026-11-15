# CREAK 데이터와 선정 문항

이 프로젝트는 [CREAK 공식 저장소](https://github.com/yasumasaonoe/creak)의 데이터를 사용합니다. 원저작자·논문 인용·사용 범위는 [THIRD_PARTY_NOTICES.md](../THIRD_PARTY_NOTICES.md), upstream MIT 라이선스 원문은 [CREAK-LICENSE.txt](../third_party/CREAK-LICENSE.txt)에 보존합니다. 프로젝트 자체의 LICENSE가 CREAK 저작권 고지를 대신하지 않습니다.

## 동봉 데이터

| 경로 | 내용 |
| --- | --- |
| `selected_data/candidates/` | CREAK dev에서 seed 123으로 추출한 참 60개·거짓 60개의 후보 풀 |
| `selected_data/curated_claims_bundle/` | 후보 풀을 검토해 선택한 참 30개·거짓 30개와 선정 기록 |

문장·원본 ID·정답은 CREAK에서 가져왔고 프로젝트의 봉투·설정·검토 기록을 추가했습니다. 선정 데이터는 공식 CREAK 분할을 대체하지 않습니다. `curation_review.json`의 검토 범위와 한계를 확인하세요. curated 메타데이터의 seed 123은 후보 풀의 샘플링 시드이며 최종 수작업 선정의 난수 시드가 아닙니다.

선정 문항과 `.meta.json`은 함께 보관합니다. Git으로 추적되는 문항 JSONL의 바이트·ID·정답·해시는 공개 준비 과정에서 변경하지 않았습니다. 개인 절대경로가 있던 메타데이터의 경로만 상대 참조로 전환했습니다.

## 원본을 사용할 때

동봉 선정 데이터로 `prepare`, `run`, `analyze`를 사용할 때는 원본이 필요하지 않습니다. 새로 샘플링하거나 원본 해시를 확인할 때만 원본을 준비하세요.

```text
dataset/
├── creak/                 원본 파일용 로컬 디렉터리 또는 심볼릭 링크 (Git 제외)
│   └── dev.jsonl
└── selected_data/         고정 선정 데이터와 메타데이터
```

Upstream의 `data/creak/dev.json`은 확장자가 `.json`인 JSONL입니다. 로더는 `.json`과 `.jsonl`을 모두 읽습니다. 아래는 확인한 upstream revision에서 새 로컬 파일을 받는 예시입니다. 기존 파일은 덮어쓰지 않으며, 이미 외부 원본 링크를 사용한다면 그 원본을 수정하지 말고 기존 파일을 사용하세요.

```python
from pathlib import Path
from urllib.request import urlopen

revision = "5e892b28b6dad3e87769cfc01f00a6577ca44068"
target = Path("dataset/creak/dev.jsonl")
if target.exists():
    raise FileExistsError(target)
url = f"https://raw.githubusercontent.com/yasumasaonoe/creak/{revision}/data/creak/dev.json"
with urlopen(url, timeout=30) as response:
    content = response.read()
target.parent.mkdir(parents=True, exist_ok=True)
with target.open("xb") as stream:
    stream.write(content)
```

CLI 사용법은 [루트 README](../README.md)를 참고하세요. 원본 파일은 입력으로만 사용하고 선정·생성 파일은 별도 디렉터리에 저장합니다.

## 메타데이터 경로

새 메타데이터는 `path_base: "artifact"`를 사용합니다. `source_path`는 해당 `.meta.json`이 있는 디렉터리 기준, `selection_path`와 `profiles_path`는 `preparation.json`이 있는 디렉터리 기준의 상대경로입니다. 원본 심볼릭 링크의 개인 컴퓨터 대상 경로를 저장하지 않습니다.

예를 들어 `selected_data/candidates/candidate_claims.meta.json`의 `source_path: "../../creak/dev.jsonl"`은 이 저장소의 `dataset/creak/dev.jsonl`을 가리킵니다. 저장소 전체를 다른 위치로 옮겨도 같은 구조에서 참조가 유지됩니다. 이전 형식의 절대경로 메타데이터는 읽기 호환성을 유지하며 자동으로 다시 쓰지 않습니다.
