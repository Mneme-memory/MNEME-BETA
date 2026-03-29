#!/usr/bin/env bash
# push-production.sh
# Pushes current state of MNEME-MAIN to the production remote (Mneme-memory/MNEME-BETA)
# as a clean single commit with no history from the personal repo.
# Also produces Mneme-release.zip — the full source + Mneme-Setup.exe in a Mneme/ folder.
#
# Usage: bash scripts/push-production.sh
# Optional message: bash scripts/push-production.sh "v15.0.0 — description"

set -e  # Exit on any error

PRODUCTION_REMOTE="production"
SOURCE_BRANCH="MNEME-MAIN"
TEMP_BRANCH="_prod_push_tmp"
DEFAULT_MSG="Mneme v15 — $(date +%Y-%m-%d)"
COMMIT_MSG="${1:-$DEFAULT_MSG}"

# Make sure we're on the right branch
CURRENT=$(git rev-parse --abbrev-ref HEAD)
if [ "$CURRENT" != "$SOURCE_BRANCH" ]; then
    echo "ERROR: Must be on $SOURCE_BRANCH (currently on $CURRENT)"
    exit 1
fi

# Make sure working tree is clean
if ! git diff --quiet || ! git diff --cached --quiet; then
    echo "ERROR: Uncommitted changes present. Commit or stash first."
    exit 1
fi

echo "Preparing clean production snapshot..."

git checkout --orphan "$TEMP_BRANCH"
git rm --cached -r . --quiet
git add .

# Verify sensitive files aren't staged
if git status --short | grep -qE "scripts/internal|CODEBASE_REVIEW|REFACTOR_OPPORTUNITIES"; then
    echo "ERROR: Sensitive files detected in staging area. Aborting."
    git checkout "$SOURCE_BRANCH"
    git branch -D "$TEMP_BRANCH"
    exit 1
fi

git commit -m "$COMMIT_MSG" --quiet
git push "$PRODUCTION_REMOTE" "$TEMP_BRANCH:$SOURCE_BRANCH" --force --quiet

git checkout "$SOURCE_BRANCH" --quiet
git branch -D "$TEMP_BRANCH" --quiet

echo "Done. Pushed to $PRODUCTION_REMOTE/$SOURCE_BRANCH as: \"$COMMIT_MSG\""

# ── Release ZIP ─────────────────────────────────────────────────────────────
EXE="Mneme-Setup.exe"
ZIP_OUT="Mneme-release.zip"
TMP_DIR="_release_tmp"

echo ""
echo "Building release ZIP..."

# Clean up temp dir on exit (even on error)
trap 'rm -rf "$TMP_DIR"' EXIT

mkdir -p "$TMP_DIR/Mneme"
git archive HEAD | tar -x -C "$TMP_DIR/Mneme"

if [ -f "$EXE" ]; then
    cp "$EXE" "$TMP_DIR/Mneme/"
else
    echo "WARNING: $EXE not found — ZIP will not include the installer."
fi

# Compress-Archive needs Windows paths
WIN_SRC=$(cygpath -w "$TMP_DIR/Mneme")
WIN_OUT=$(cygpath -w "$(pwd)/$ZIP_OUT")
powershell -NoProfile -Command "Compress-Archive -Path '$WIN_SRC' -DestinationPath '$WIN_OUT' -Force"

echo "Release ZIP: $ZIP_OUT"
echo ""
echo "To publish: gh release create vX.Y.Z $ZIP_OUT $EXE GIVE-TO-CLAUDE-FOR-HELP.pdf --repo Mneme-memory/MNEME-BETA --title \"Mneme vX.Y.Z\" --notes \"...\""
