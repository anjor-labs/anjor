#!/usr/bin/env bash
# Pre-commit safety check: block internal/sensitive files from the public repo.
# Runs via pre-commit framework — do not invoke directly in CI.
#
# Blocks:
#   .internal/**     — internal planning docs (NEXT_STAGE.md, etc.)
#   .claude/**       — Claude Code settings, hooks, plans
#   CLAUDE.md        — project brief with internal details
#   *.db / *.db-shm / *.db-wal / *.sqlite* — database artifacts
#
# All of these are already in .gitignore. This hook is belt-and-suspenders:
# it catches the case where someone stages a file with `git add -f`.

set -euo pipefail

BLOCKED_PATTERNS=(
    "^\.internal/"
    "^\.claude/"
    "^CLAUDE\.md$"
    "\.db$"
    "\.db-shm$"
    "\.db-wal$"
    "\.sqlite$"
    "\.sqlite3$"
)

STAGED=$(git diff --cached --name-only --diff-filter=ACMRT 2>/dev/null) || true

if [ -z "$STAGED" ]; then
    exit 0
fi

VIOLATIONS=()
while IFS= read -r file; do
    for pattern in "${BLOCKED_PATTERNS[@]}"; do
        if echo "$file" | grep -qE "$pattern"; then
            VIOLATIONS+=("  ✗  $file  (matches: $pattern)")
            break
        fi
    done
done <<< "$STAGED"

if [ ${#VIOLATIONS[@]} -gt 0 ]; then
    echo ""
    echo "BLOCKED: The following files must not be committed to the public repo:"
    printf '%s\n' "${VIOLATIONS[@]}"
    echo ""
    echo "These files contain internal plans, configs, or database artifacts."
    echo "All of these paths are already in .gitignore."
    echo "If they are staged, someone used 'git add -f' — remove them first:"
    echo ""
    echo "  git restore --staged <file>"
    echo ""
    echo "To bypass intentionally (use with extreme caution):"
    echo "  git commit --no-verify"
    exit 1
fi

exit 0
