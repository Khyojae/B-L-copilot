# [BE 요청] 판정(Verdict)에 원인 필드 컬럼 추가 + 메시지 필드 표기 정책

> 백엔드 담당자에게 보내는 요청 문서입니다.
> FE가 지금 문자열 매칭으로 우회하고 있는 부분이 있어, 스키마 한 칸이 추가되면
> 그 우회를 걷어낼 수 있습니다.
>
> M-1·M-2(`M1_M2_팀확정요청.md`)와는 성격이 다릅니다. 그쪽은 FE 내부 규칙을
> 팀이 확정해 달라는 것이고, 이 문서는 **API 응답 스키마 제안**입니다.

---

## 1. 요청: `Verdict`에 원인 필드를 담는 컬럼

### 무엇이 필요한가

판정 결과가 `DEFERRED`(판정 보류)일 때, **무엇 때문에 보류됐는지**를 담을 자리가
없습니다. 지금 `Verdict`는 이렇습니다 (`src/types/domain.ts`):

```ts
export interface Verdict {
  verdict_id: string;
  rule_id: string;
  target_fields: string[];   // 이 판정이 "검사한" 필드
  result: 'VIOLATION' | 'PASS' | 'DEFERRED';
  severity: 'Critical' | 'Warning' | 'Info';
  message: string;
  action_hint: string | null;
  evidence: { clause_text: string; event_ids?: string[] };
  judged_at: string;
  rule_version: string;
  model_version: string | null;
}
```

`target_fields`는 **검사 대상**입니다. 보류를 일으킨 필드는 별개입니다.

실제 예 (`R-XREF-QTY`):

| | 값 |
|---|---|
| `target_fields` | `['no_of_packages']` — 포장 수량을 검사하려 했음 |
| 보류 원인 | `measurement` — 용적이 "필수 확인"이라 교차 검사를 못 돌림 |
| `message` | "포장 수량 교차 검사가 보류되었습니다. 용적 필드가 필수 확인 상태입니다." |

보류 원인이 `measurement`라는 사실이 **오직 메시지 문장 안에만** 있습니다.

### 제안

```ts
export interface Verdict {
  // ...기존 필드...

  /**
   * 이 판정이 보류(DEFERRED)된 원인 필드.
   * result가 'DEFERRED'가 아니면 빈 배열.
   */
  blocked_by: string[];
}
```

이름은 `blocked_by`가 아니어도 됩니다 (`deferred_by`, `blocking_fields` 등).
필요한 건 **원인 필드를 식별자로 내려주는 것**입니다.

---

## 2. FE가 지금 어떻게 우회하고 있는가

`src/pages/S6Alerts/DeferredCard.tsx`에서 **판정 메시지 문자열을 훑어서** 원인
필드를 찾습니다.

```ts
const blockingField = fields.find(
  (field) =>
    field.field_name !== targetName &&
    (verdict.message.includes(labelOfField(field.field_name)) ||
      verdict.message.includes(field.field_name)) &&
    effectiveGradeOf(field, {}) === 'REQUIRED',
);
```

즉 **"메시지에 그 필드 이름이 들어 있으면 그게 원인"** 이라고 추측합니다.

### 이 방식이 실제로 깨진 적이 있습니다

목데이터의 판정 메시지를 영문 필드명에서 한글 라벨로 바꾸는 작업을 했습니다.

```
변경 전: "... measurement 필드가 필수 확인 상태입니다."
변경 후: "... 용적 필드가 필수 확인 상태입니다."
```

문구만 바꿨는데 **화면의 "보류 원인" 칸이 통째로 사라졌습니다.** 매칭 대상이
`measurement`였기 때문입니다. 지금은 한글 라벨과 영문 식별자를 둘 다 확인하도록
임시로 넓혀뒀지만, 문장 표현이 바뀌면(예: "용적" 대신 "부피") 또 깨집니다.

### 이 우회가 만드는 문제

- 메시지 문구를 고칠 때마다 화면이 조용히 깨집니다. 에러가 안 나고 칸만 사라져서
  발견이 늦습니다.
- 원인 필드로 바로 이동하는 링크(`?focus=<field_name>`)도 같이 사라집니다.
  사용자가 "무엇을 고쳐야 하는지"를 알 수 없게 됩니다.
- 필드 이름이 다른 필드 이름의 일부인 경우 오탐이 납니다
  (예: `port_of_loading`과 `port_of_discharge`).

---

## 3. 함께 정해야 할 것 — 판정 메시지의 필드 표기

### 문제

`message`·`action_hint`는 **백엔드가 만들어 내려주는 문자열**입니다. 지금은
목데이터라 FE가 고쳤지만, 실제 API가 붙으면 **같은 문제가 그대로 돌아옵니다.**

FE는 화면의 모든 필드 이름을 한글 표시명으로 통일했습니다
(`src/constants/domain.ts`의 `FIELD_LABEL`, 26개 필드).

```
port_of_loading  → 선적항
measurement      → 용적
container_no     → 컨테이너 번호
no_of_packages   → 포장 수량
```

그런데 판정 메시지에 `measurement` 같은 영문 식별자가 섞여 오면, **같은 필드가
한 화면에서 두 이름으로 보입니다.** 필드 목록에는 "용적", 판정 메시지에는
"measurement"로 나오는 식입니다.

### 선택지

**(가) 백엔드가 한글 표시명으로 메시지를 만든다**
- FE는 받은 문자열을 그대로 씁니다. 가장 단순합니다.
- 표시명 사전을 BE·FE가 각자 들고 있게 되어 어긋날 수 있습니다.
  → 사전을 한쪽이 소유하고 다른 쪽이 받아 쓰는 방식이 필요합니다.

**(나) 백엔드는 식별자로 주고, FE가 치환한다**
- 예: `"{{no_of_packages}} 교차 검사가 보류되었습니다. {{measurement}} 필드가…"`
- FE가 `FIELD_LABEL`로 치환합니다. 표시명 사전은 FE가 단독 소유합니다.
- 다국어로 갈 때도 이 방식이 맞습니다.
- 대신 메시지 포맷을 BE·FE가 약속해야 합니다.

**(다) 메시지를 문장이 아니라 구조로 준다**
- 예: `{ template: 'XREF_DEFERRED', params: { target: 'no_of_packages', blocked_by: 'measurement' } }`
- 가장 튼튼하지만 작업량이 가장 큽니다.

FE 입장에서는 **(나)** 가 무난해 보입니다. 표시명을 한 곳에서만 관리할 수 있고,
1번 요청(`blocked_by`)이 반영되면 문자열 매칭도 같이 사라집니다. 다만 이건
백엔드 사정에 따라 달라질 수 있어 결정을 요청드립니다.

---

## 4. 정리

| # | 요청 | 급한 정도 |
|---|---|---|
| 1 | `Verdict`에 보류 원인 필드(`blocked_by` 등) 추가 | 높음 — 지금 문자열 매칭으로 우회 중이고 이미 한 번 깨졌습니다 |
| 2 | 판정 메시지의 필드 표기 정책 결정 (가/나/다) | 중간 — 실제 API 연동 전까지 |

1번이 반영되면 FE는 `DeferredCard.tsx`의 문자열 매칭을 지우고 `blocked_by`를
그대로 씁니다. 그 외 변경은 없습니다.

관련 파일:
- `src/types/domain.ts` — `Verdict` 정의
- `src/pages/S6Alerts/DeferredCard.tsx` — 우회 코드 위치
- `src/constants/domain.ts` — `FIELD_LABEL` (26개 표시명)
