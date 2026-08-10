#!/usr/bin/env bash
#
# Smart_e-BL_Backend → Smart_e-BL(develop)/backend/ 동기화
#
# 이 저장소의 내용을 통합 저장소의 backend/ 폴더로 옮기고 PR을 연다.
# 로컬에서도 CI(.github/workflows/sync-to-monorepo.yml)에서도 이 스크립트를 쓴다.
# 동작이 갈리면 디버깅이 두 배로 힘들어지므로 진입점을 하나로 유지한다.
#
# 사용법:
#   ./scripts/sync-to-monorepo.sh              # 동기화 후 PR 생성
#   ./scripts/sync-to-monorepo.sh --dry-run    # 전송 대상만 출력하고 종료
#
# 요구사항: git, gh(인증됨). rsync는 쓰지 않는다 — 아래 참고.
#
# ── 왜 rsync가 아니라 git archive인가 ──────────────────────────────
# rsync는 --exclude 목록을 사람이 관리해야 하고, 빠뜨리면 조용히 유출된다.
# git archive는 '추적 중인 파일'만 내보내므로 다음이 구조적으로 보장된다:
#   - api/certs/ 의 개발용 CA 개인키 (untracked)  → 애초에 포함 불가
#   - .env (gitignore)                            → 애초에 포함 불가
#   - node_modules, __pycache__ (gitignore)       → 애초에 포함 불가
# 제외 규칙을 유지보수할 필요가 없어지고, Git Bash에 rsync가 없는 문제도 사라진다.

set -euo pipefail

MONOREPO="${MONOREPO:-SmartBLAI/Smart_e-BL}"
TARGET_BRANCH="${TARGET_BRANCH:-develop}"
TARGET_DIR="${TARGET_DIR:-backend}"

DRY_RUN=0
[[ "${1:-}" == "--dry-run" ]] && DRY_RUN=1

SRC_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$SRC_ROOT"

# 추적 중이지만 통합 저장소로 보낼 이유가 없는 것들.
# (유출 위험 때문이 아니라 중복·오작동 방지 목적)
#   .github/  : 이 워크플로가 통합 저장소에서 또 돌면 안 된다
#   scripts/sync-to-monorepo.sh : 동기화 도구 자신
PRUNE_AFTER_EXTRACT=(
  '.github'
  'scripts/sync-to-monorepo.sh'
)

log()  { printf '\033[36m▶\033[0m %s\n' "$*"; }
ok()   { printf '\033[32m✓\033[0m %s\n' "$*"; }
warn() { printf '\033[33m!\033[0m %s\n' "$*"; }
die()  { printf '\033[31m✗\033[0m %s\n' "$*" >&2; exit 1; }

command -v gh >/dev/null || die "gh CLI가 필요합니다. https://cli.github.com"

SHA="$(git rev-parse --short HEAD)"
SRC_BRANCH="$(git rev-parse --abbrev-ref HEAD)"
SYNC_BRANCH="sync/backend-${SHA}"

# 추적 파일 트리를 dest에 펼친다.
export_tree() {
  local dest="$1"
  mkdir -p "$dest"
  git archive --format=tar HEAD | tar -x -C "$dest"
  for p in "${PRUNE_AFTER_EXTRACT[@]}"; do
    rm -rf "${dest:?}/${p}"
  done
}

if [[ $DRY_RUN -eq 1 ]]; then
  log "DRY RUN — 전송 대상 (${MONOREPO} ${TARGET_BRANCH} → ${TARGET_DIR}/)"
  echo
  tmp="$(mktemp -d)"
  trap 'rm -rf "$tmp"' EXIT
  export_tree "$tmp"

  ( cd "$tmp" && find . -type f | sed 's|^\./||' | sort )
  echo
  log "총 $(find "$tmp" -type f | wc -l | tr -d ' ')개 파일"

  echo
  log "민감 항목 검증"
  fail=0
  # 디렉토리·파일 양쪽을 본다. certs 는 디렉토리, .env 는 파일.
  for pat in 'certs' '.env' 'node_modules' '__pycache__' '.venv'; do
    if find "$tmp" -name "$pat" -print -quit | grep -q .; then
      printf '  \033[31m✗ %s 포함됨 — 확인 필요\033[0m\n' "$pat"; fail=1
    else
      printf '  \033[32m✓ %s 없음\033[0m\n' "$pat"
    fi
  done
  for ext in 'pem' 'key'; do
    if find "$tmp" -name "*.${ext}" -print -quit | grep -q .; then
      printf '  \033[31m✗ *.%s 포함됨 — 확인 필요\033[0m\n' "$ext"; fail=1
    else
      printf '  \033[32m✓ *.%s 없음\033[0m\n' "$ext"
    fi
  done
  echo
  [[ $fail -eq 0 ]] && ok "제외 규칙 정상" || die "민감 파일이 전송 대상에 포함되어 있습니다."
  exit 0
fi

# 워킹트리가 지저분하면 무엇이 동기화됐는지 나중에 특정할 수 없다.
# (git archive는 HEAD를 기준으로 하므로 미커밋 변경은 어차피 반영되지 않는다)
if [[ -n "$(git status --porcelain --untracked-files=no)" ]]; then
  die "커밋되지 않은 변경이 있습니다. 커밋하거나 stash한 뒤 다시 실행하세요."
fi

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

log "통합 저장소 클론: ${MONOREPO} (${TARGET_BRANCH})"
gh repo clone "$MONOREPO" "$WORK/monorepo" -- --branch "$TARGET_BRANCH" --depth 1 --quiet \
  || die "클론 실패. ${MONOREPO} 접근 권한을 확인하세요."

cd "$WORK/monorepo"
git checkout -b "$SYNC_BRANCH" --quiet

# 이전 동기화분을 지우고 새로 펼친다. 원본에서 삭제된 파일이
# 통합 저장소에 남는 것을 막기 위해 통째로 교체한다.
log "이전 내용 제거 → ${TARGET_DIR}/"
git rm -rq --ignore-unmatch "$TARGET_DIR"
rm -rf "${TARGET_DIR:?}"

log "git archive 전개 → ${TARGET_DIR}/"
( cd "$SRC_ROOT" && git archive --format=tar HEAD ) | ( mkdir -p "$TARGET_DIR" && tar -x -C "$TARGET_DIR" )
for p in "${PRUNE_AFTER_EXTRACT[@]}"; do
  rm -rf "${TARGET_DIR:?}/${p}"
done

# 통합 저장소가 backend/.gitkeep 으로 폴더 자리를 잡아둔 상태라
# 비어 있게 되는 경우 되살려 둔다.
[[ -z "$(ls -A "$TARGET_DIR" 2>/dev/null)" ]] && touch "$TARGET_DIR/.gitkeep"

git add -A "$TARGET_DIR"
if git diff --cached --quiet; then
  ok "변경 사항 없음 — 통합 저장소가 이미 최신입니다."
  exit 0
fi

git -c user.name="${GIT_AUTHOR_NAME:-sync-bot}" \
    -c user.email="${GIT_AUTHOR_EMAIL:-sync-bot@users.noreply.github.com}" \
    commit --quiet -m "sync(backend): Smart_e-BL_Backend@${SHA} 반영

원본 브랜치: ${SRC_BRANCH}
scripts/sync-to-monorepo.sh 로 생성된 커밋입니다."

log "push: ${SYNC_BRANCH}"
git push --quiet -u origin "$SYNC_BRANCH"

PR_URL="$(gh pr create \
  --repo "$MONOREPO" \
  --base "$TARGET_BRANCH" \
  --head "$SYNC_BRANCH" \
  --title "sync(backend): Smart_e-BL_Backend@${SHA}" \
  --body "$(cat <<EOF
백엔드 저장소의 작업 결과를 \`${TARGET_DIR}/\`로 동기화합니다.

| | |
|---|---|
| 원본 | \`Smart_e-BL_Backend@${SHA}\` (\`${SRC_BRANCH}\`) |
| 생성 | \`scripts/sync-to-monorepo.sh\` |

\`git archive\`로 **추적 중인 파일만** 내보냅니다. 따라서 \`api/certs/\`의 개발용 CA 개인키,
\`.env\`, \`node_modules\` 는 구조적으로 포함되지 않습니다.

이 PR은 스크립트가 자동 생성했습니다. 코드 검토는 원본 저장소의 PR에서 이루어집니다.
EOF
)")"

ok "PR 생성 완료: $PR_URL"
