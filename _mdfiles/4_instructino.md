현재 `moral-memory-eval` 프로젝트에서 OpenAI Responses API의 `reasoning.effort`를 명시적으로 지정할 수 있도록 수정해 줘.

요구사항:

1. GPT-6 Luna의 `reasoning.effort`를 `medium`으로 고정하여 본실험에서 사용하려고 한다.
2. `prepare` CLI에 선택적 `--reasoning-effort` 옵션을 추가한다.
3. 지원하는 값은 `none`, `low`, `medium`, `high`, `xhigh`, `max`이다.
4. 지정하지 않은 기존 요청과의 하위 호환성을 유지한다.
5. OpenAI Responses API에는 `reasoning={"effort": "medium"}` 형식으로 전달한다.
6. 생성 설정을 `requests.jsonl`과 `preparation.json`에 기록하고, 실행 및 Resume 검증에도 반영한다.
7. Gemini 등 해당 옵션을 지원하지 않는 제공자에서 조용히 무시하지 않고 명확한 오류를 발생시키거나 적절한 호환성 처리를 구현한다.
8. 기존 `llmkit` 구조를 가능한 한 유지하고, Mock 기반 자동 테스트를 추가한다.
9. 기존 준비 데이터나 결과 파일은 수정하거나 덮어쓰지 않는다.

수정 후 GPT-6 Luna를 `medium`으로 설정하는 실제 `prepare` 명령어를 알려줘.