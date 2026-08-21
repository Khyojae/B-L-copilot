/**
 * ⓘ 툴팁 — 룰 코드(R-XREF-QTY), 문서 ID(DOC-002), 이벤트 코드(EVT-003 · DCSA)처럼
 * 평소엔 필요 없지만 문의·디버깅에는 있어야 하는 값을 접어둡니다.
 *
 * title 속성만 씁니다. 커스텀 툴팁을 만들면 키보드·모바일 대응을 따로 해야
 * 하는데, 브라우저 기본 툴팁은 그게 이미 됩니다.
 */
export function InfoTip({ text }: { text: string }) {
  return (
    <span
      title={text}
      aria-label={text}
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        justifyContent: 'center',
        width: 16,
        height: 16,
        flexShrink: 0,
        borderRadius: 999,
        border: '1.5px solid var(--border-default)',
        fontSize: 10,
        fontWeight: 700,
        lineHeight: 1,
        color: 'var(--text-secondary)',
        cursor: 'help',
      }}
    >
      i
    </span>
  );
}
