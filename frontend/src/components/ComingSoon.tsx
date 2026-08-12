interface ComingSoonProps {
  /** 어느 화면 자리인지 표시할 이름. 예: "S2 서류 업로드" */
  label: string;
}

/** 아직 만들지 않은 화면의 자리만 잡아두는 임시 컴포넌트 */
export function ComingSoon({ label }: ComingSoonProps) {
  return (
    <div style={{ padding: 32, textAlign: 'center' }}>
      <p>{label} 화면 준비 중입니다.</p>
    </div>
  );
}
