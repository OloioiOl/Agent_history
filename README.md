# Agent History

**LLM 중계의 데이터 변형을 줄이기 위해, 원문 전달과 결과 검증을 코드로 옮긴 개인 에이전트 운영 프로젝트.**

> *A personal agent-ops project that moved source delivery and result verification out of an LLM relay and into code: a sandboxed Unix-socket bridge that lets Hermes delegate document analysis to agy and checks every returned quotation against the source.*

```mermaid
flowchart LR
    U[Discord 사용자] --> H[Hermes: 호출 판단]
    H --> P[bulk_analyze: 허용 파일 읽기]
    P --> B[Unix 소켓 · systemd 브리지]
    B --> A[agy: 원문 분석]
    A --> V[구조 · 한도 · 인용 검사]
    V --> H
    H --> U
```

- **만든 것:** Hermes가 agy에 분석을 위임하는 로컬 브리지와 플러그인. 기존 독립 agy Discord 봇과 함께 운영한다.
- **핵심 설계:** 경로별 파일 열기, 소켓 peer UID 확인, systemd 제한, 출력·정리 시간 제한, 구조화 결과 검사.
- **확인한 결과:** 16KB 실제 분석·인용 반환, 운영 Discord 경로 거절 응답, 브리지 `enabled`·`active`.

## 왜 만들었나

초기에는 Hermes의 중계 모델이 `!pro`를 명령으로 분기하기보다 의미를 분석하거나, Gemini Pro의 응답을 새 사용자 지시처럼 다시 처리하는 경우가 있었다. 두 모델 사이의 컨텍스트 차이도 중계의 제약이었다. 사용자 경험을 바탕으로 환경을 초기화하고 **프롬프트 중계 → 독립 봇 → 코드 기반 위임**으로 구조를 바꿨다.

이 저장소는 그 설계 판단과 실패 수정의 기록이다. 개인 운영 메모와 기술 포트폴리오를 함께 목적으로 하며 범용 설치 배포판은 아니다.

## 먼저 볼 문서

| 관심사 | 문서 |
|---|---|
| 보안 설계 | [위협 모델](docs/10-threat-model.md) · [systemd·설정 예시](examples/README.md) |
| 실패에서 배운 것 | [157KB 실패와 도구 시도](docs/03-incidents.md#incident-large-input) · [반환 계약 오류](docs/03-incidents.md#incident-result-contract) |
| 직접 내린 판단 | [결정 기록](docs/08-decisions.md) · [연대기](docs/01-history.md) |
| 근거와 신뢰 범위 | [검증 현황](docs/04-validation.md) · [출처·AI 협업](docs/06-provenance.md) |
| 다음 작업·운영 | [다음 시험](docs/05-next-validation.md) · [운영 메모](docs/09-operations.md) |

[상세 구조](docs/02-architecture.md) · [공개 기록 원칙](docs/07-publication.md) · [NOTICE](NOTICE.md)

## 검증 경계

**2026-10-08 기준:** 16,384바이트 실제 분석 성공은 이전 실행 기록이고, 157,547바이트 분석은 여전히 실패다. 운영 Discord에서는 `PATH_DENIED` 반환을 확인했으며, 정상 문서 분석 전체 경로와 최종 답변의 내용 보존은 아직 미검증이다.

인용 일치가 의미적 정확성을 보증하지 않으며, 도구 감지는 관측 후 중단이다. 완전한 격리·프롬프트 인젝션 방어·비용 절감을 입증한 프로젝트로 소개하지 않는다. 용어와 성공 기준은 [검증 경계 정의](docs/04-validation.md#verification-boundaries)에 모았다.

## 코드 확인

`bridge/`는 schema-r3 소스와 JSON 문자열 반환 수정본이다. 서버에서 전체 소스를 새로 수집한 스냅샷은 아니며, 독립 Discord 봇·Hermes 본체·agy 바이너리는 포함하지 않는다.

**Python 3.11 이상.** 아래 명령은 모델 호출과 서비스 변경 없이 실행한다.

```bash
cd bridge
python -m unittest -v test_bridge.Validation test_result_contract
```

Linux 임시 환경에서 fake 프로세스·Unix 소켓 시험까지 수행하려면:

```bash
cd bridge
python -m unittest -v test_bridge test_result_contract
```

초기 저장소 확인은 Windows **19개 통과·Linux 전용 12개 skip**이었다. [당시 기록](evidence/local-checks.json)과 [문서 보강 검사](evidence/review-checks.json)를 구분한다. [외부 검증자의 Python 3.10 보고](docs/04-validation.md#external-review)는 별도 참고 기록이다.

실제 서버 명령과 Discord 시험은 사용자가 수행했고 AI가 설계·코드·분석을 보조했다. 과거 커밋 이력을 소급 생성하지 않았으며, 코드 공개 라이선스는 아직 지정하지 않았다.
