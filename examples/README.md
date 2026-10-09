# systemd 및 설정 예시

**기록된 유닛에서 경로·계정 이름을 일반화한 검토용 예시다. 새 서버에 설치하거나 검증한 구성은 아니다.** JSON 키는 포함된 코드가 실제로 읽는 키와 맞췄다. 자동 설치·실제 모델 실행 명령은 제공하지 않는다.

| 파일 | 읽는 코드 / 실제 이름 |
|---|---|
| [client.example.json](client.example.json) | 플러그인 옆의 `client.json`; `__init__.py`, `bulk_analyze_client.py` |
| [config.example.json](config.example.json) | 서비스 `--config` 경로의 `config.json`; `bridge_service.py` |
| [agy-bridge.service.example](agy-bridge.service.example) | 운영 전 검토할 systemd unit 템플릿 |

`.example.json`은 공개 가능한 가상 값이고, 실제 `client.json`·`config.json`은 `.gitignore` 대상이다. 계정 이름·UID·디렉터리가 이미 존재한다고 가정하면 안 된다.

## 이 예시의 경로 대응

| 의미 | 예시 경로 |
|---|---|
| 호스트 Hermes 데이터 디렉터리 | `/srv/hermes-data` |
| 컨테이너 bind mount 목적지 | `/opt/data` |
| 허용 입력: 호스트 / 컨테이너 | `/srv/hermes-data/bulk-inbox` / `/opt/data/bulk-inbox` |
| 소켓: 호스트 / 컨테이너 | `/srv/hermes-data/run/agy-bridge/bridge.sock` / `/opt/data/run/agy-bridge/bridge.sock` |
| 소켓: 서비스 mount namespace | `/run/agy-bridge-host/socketdir/bridge.sock` |
| 서비스 코드 / 설정 / 결과 | `/opt/agy-bridge` / `/etc/agy-bridge` / `/var/lib/agy-bridge/results` |
| agy 실행·인증 계정 | 가상의 `bridge-worker`; 인증은 해당 계정의 `.gemini` 경로 |

`BindPaths`는 전용 소켓 디렉터리만 서비스 namespace에 연결한다. 컨테이너 쪽 mount와 systemd 쪽 bind는 서로 다른 두 설정이다.

## 필요한 권한 전제

- `allowed_uids: [11000]`은 **예시 숫자**다. 소켓 서버가 보는 실제 Hermes peer UID와 일치해야 한다. user namespace/remap을 쓴다면 별도로 확인한다.
- 예시에서 Hermes UID/GID를 11000:11000, bridge-worker UID/GID를 12000:12000으로 가정한다. 실제 계정 생성이나 ID 할당은 이 저장소가 수행하지 않는다.
- 기존 운영 설계처럼 소켓 호스트 디렉터리는 bridge-worker 소유, Hermes가 접근 가능한 그룹, setgid를 가진 2710 모드로 구성하는 방법이 있다. 예시 숫자로는 12000:11000이다. 소켓은 서비스가 0660으로 생성하며 그룹 상속과 양쪽 경로 접근을 실제 확인해야 한다.
- 결과 디렉터리는 실행 계정 소유의 0700이어야 한다. 서비스 코드의 `serve()`가 이를 검사한다. 상위 작업 디렉터리도 실행 계정이 접근할 수 있어야 한다.
- 코드·설정은 관리자가 관리하고 필요한 실행 계정에만 읽기 권한을 준다. 허용 입력 폴더에는 분석을 허용한 문서만 둔다.
- `.gemini`, 결과, 소켓 bind 원본, 차단할 봇 디렉터리는 검토된 실제 경로로 준비해야 한다. 경로가 없으면 서비스가 실패할 수 있다.
- `/usr/bin/python3`가 Python 3.11 이상인지 확인한다. agy CLI 옵션과 `bridge_core.MODELS`의 모델 ID는 당시 스냅샷이므로 새 환경에서는 도움말·지원 여부를 다시 확인한다.

## 유닛이 표현하는 통제

| 설정 | 목적 | 한계 |
|---|---|---|
| `InaccessiblePaths` | 지정 봇 디렉터리를 서비스 namespace에서 차단 | 다른 경로에 복사된 토큰이나 허용 인증 경로까지 차단하지 않음 |
| `ProtectSystem=strict` + `ReadWritePaths` | 쓰기 가능 경로를 제한 | 파일 내용 읽기·네트워크 차단을 의미하지 않음 |
| `PrivateTmp` | 서비스에 별도의 임시 디렉터리 공간 제공 | 전체 파일시스템·동일 UID 프로세스 격리와 다름 |
| `NoNewPrivileges` | 실행 후 새 권한 획득 제한 | 이미 가진 권한을 모두 제거하는 설정은 아님 |
| `KillMode=control-group` | 서비스 중지 시 자식 프로세스 정리 범위 | 요청 단위 process-group 정리와 구분 |
| `MemoryMax`, `TasksMax`, `TimeoutStopSec` | 서비스 자원·정지 제한 | 모델 토큰 비용 상한이나 다른 봇과의 공통 제한이 아님 |

기록된 설정은 인증 경로와 네트워크를 계속 허용한다. 완전한 sandbox로 소개하지 않는다. [위협 모델](../docs/10-threat-model.md)의 T3·T4·T6·T7과 함께 읽는다.

## 설정 키

- client: `socket`은 컨테이너에서 접근할 Unix 소켓, `roots`는 alias → 절대 디렉터리 mapping이다. 도구 인자는 `inbox/<상대경로>` 형태다.
- service: `socket`, `results`, `agy`, `allowed_uids`가 필요하다. `timeout_seconds` 기본값은 630이며 CLI 내부 값은 코드에서 600초로 지정한다.
- service의 선택 키 `socket_gid`도 코드에 있지만 이 예시는 setgid 디렉터리 상속을 사용하므로 생략했다. 해당 키를 사용할 경우 실행 계정의 그룹 변경 권한을 확인해야 한다.
- stdout·stderr·반환 한도·보존 일수 등은 현재 코드 상수/로직이다. 미지원 설정 키를 JSON에 추가해 바뀌는 것처럼 설명하지 않는다.

이번 검사는 JSON 파싱, 코드의 키 사용, 경로 대응, 원본 유닛과의 치환 비교를 확인한다. Linux `systemd-analyze verify`, 권한 준비, 서비스 시작, 재부팅 검증은 이 예시에 대해 수행하지 않았다.
