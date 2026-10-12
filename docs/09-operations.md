# 개인 운영 메모

이 문서는 운영 대상을 구분하기 위한 메모다. 배포 스크립트가 아니며 기존 서버에 소스 파일을 그대로 덮어쓰지 않는다.

## 구성요소 구분

| 대상 | 이름 | 담당 |
|---|---|---|
| Docker 컨테이너 | `hermes` | 오케스트레이터와 gateway |
| 독립 봇 systemd 서비스 | `agy-discord-bot.service` | Discord의 agy 전용 명령 |
| 브리지 systemd 서비스 | `agy-bridge.service` | Unix 소켓 분석 요청 |
| Hermes 플러그인 | `bulk-analyze` | 도구 등록과 파일 읽기 |
| 도구/도구 묶음 | `bulk_analyze` | Hermes의 분석 위임 호출 |
| prefix guard | `agy-prefix-guard` | 지정 명령에 대한 Hermes 중복 반응 방지 |

플러그인의 하이픈 이름과 도구의 밑줄 이름을 혼동하지 않는다. 봇의 동시 실행 제한과 브리지의 제한은 별개다.

## 읽기 전용 상태 확인

아래는 Ubuntu 서버에서 사용자가 실행하는 조회 예시다. 모델을 호출하거나 서비스를 바꾸지 않는다.

```bash
docker inspect hermes --format 'running={{.State.Running}} started={{.State.StartedAt}} restart_count={{.RestartCount}}'
systemctl is-active agy-discord-bot.service
systemctl is-active agy-bridge.service
systemctl is-enabled agy-bridge.service
```

컨테이너 running만으로 Discord connected를 판정하지 않는다. 설치본 gateway 상태 파일의 PID 신원과 platform 상태를 함께 봐야 한다. 이번 버전에서는 `gateway_state.json`을 사용했지만 후속 버전의 파일명·API는 확인해야 한다. 2026-10-11 진단에서 상태 파일의 `hermes_home` 필드가 없었으므로 단순 문자열 비교의 false를 경로 오류로 판정하지 않았다. 설치본 API의 PID 시작 시각·홈 범위 검사를 함께 확인했다.

## 변경과 복구 원칙

1. 현재 파일과 설치본 API, 실행 사용자, mount를 확인한다.
2. 원본과 후보를 백업하고 해시를 기록한다.
3. 작은 범위의 변경 뒤 실제 dispatcher까지 확인한다.
4. gateway 재시작이 필요한 변경과 서비스 enable만 필요한 변경을 구분한다.
5. 복구 명령은 정상 적용 명령과 분리한다. 적용 후 다른 수정이 있으면 과거 백업을 무조건 덮어쓰지 않는다.

이번 환경의 활성화/재적용 스크립트는 수정 전 플러그인 해시를 고정했다. 반환 계약을 고친 현재 상태에서 옛 스크립트를 다시 실행하면 안 된다. 코드 스냅샷의 `test_plugin_registration_contract`만으로 설치본 dispatcher 반환 계약을 확인했다고 판단하지 않는다.

## 기록을 찾는 순서

현재 상태는 `docs/04-validation.md`, 사건의 이유는 `docs/03-incidents.md`, 판단은 `docs/08-decisions.md`, 원본 자료의 종류는 `docs/06-provenance.md`에서 찾는다. 이 공개본에는 실제 서버의 인증정보·연결 주소·원본 데이터 보관 위치를 넣지 않았다. 개인 비공개 운영 문서에서 별도로 관리한다.

## 다음 세션에 전달할 짧은 맥락

> 2026-10-11 프로젝트 문서 5,807바이트의 첫 시도는 근거 수 초과로 실패했다. 호스트 브리지의 프롬프트에 기존 상한을 명시한 뒤 두 번째 시도에서 정상 경로와 인용 14개 보존을 확인했다. Linux Python 3.12.3 fake 시험은 31개 모두 통과했다. 157KB 실패·대표 강의 문서 품질·재부팅 복구는 미해결/미검증으로 유지한다. 완료된 모델 호출과 옛 설치 스크립트를 반복하지 않는다.

현재 호스트 core는 `42f3d034eca6b45ece58566fcf017f60fb3dc6bb3d01273c81bc1ec6c13421f5`다. 클라이언트 플러그인의 core는 기존 `1239223b39628b77f609a403772fb35719b85def702cae0eb0b2044edb3bb737`를 유지한다. 차이는 호스트가 사용하는 프롬프트 문구이며 스키마·검증 코드는 같다. 따라서 과거 진단의 호스트 해시 고정값으로 재검사하면 불일치가 나는 것이 예상된다. 적용했던 스크립트를 그대로 반복하지 말고 현재 해시·백업을 먼저 확인한다.
