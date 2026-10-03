#!/usr/bin/env bash
# Structured, safe S3 upload for DNA-Blockchain / Rabbit Software.
# Dry-run by default. Pass --apply to actually upload.
#
# Usage:
#   scripts/s3_structured_upload.sh <source_dir> <kind> [--apply]
#   kind: exe | zip | json | py | software | data | research
#   research -> public/research/ (sanitized metadata only; public-readable prefix)
#
# Env:
#   RABBIT_S3_BUCKET  target bucket (default: amzn-s3-rabbit-software)
#   AWS_PROFILE       SSO profile to use (run `aws sso login` first)
set -euo pipefail

SRC="${1:?source dir required}"
KIND="${2:?kind required: exe|zip|json|py|software|data}"
APPLY="${3:-}"
BUCKET="${RABBIT_S3_BUCKET:-amzn-s3-rabbit-software}"

[ -d "$SRC" ] || { echo "Not a directory: $SRC" >&2; exit 1; }

case "$KIND" in
  exe)      DEST="s3://$BUCKET/"          ; INC=(--include "*.exe") ;;
  zip)      DEST="s3://$BUCKET/"          ; INC=(--include "*.zip") ;;
  json)     DEST="s3://$BUCKET/"          ; INC=(--include "*.json") ;;
  py)       DEST="s3://$BUCKET/"          ; INC=(--include "*.py") ;;
  software) DEST="s3://$BUCKET/software/" ; INC=(--include "*") ;;
  data)     DEST="s3://$BUCKET/data/"     ; INC=(--include "*") ;;
  # Only public/ is meant to be world-readable (see scripts/s3_public_prefix_policy.json).
  research) DEST="s3://$BUCKET/public/research/" ; INC=(--include "*.json" --include "*.csv" --include "*.md" --include "*.txt" --include "*.parquet") ;;
  *) echo "Unknown kind: $KIND" >&2; exit 1 ;;
esac

# Excludes come last so they always win over the includes above.
SAFE_EXCLUDES=(
  --exclude ".git/*" --exclude "*/.git/*"
  --exclude ".env" --exclude ".env.*" --exclude "*/.env" --exclude "*/.env.*"
  --exclude "*.pem" --exclude "*.key" --exclude "*.p12" --exclude "*.pfx"
  --exclude "*id_rsa*" --exclude "*id_ed25519*"
  --exclude "*credential*" --exclude "*secret*" --exclude "*token*" --exclude "*password*"
  --exclude "*.db" --exclude "*.sqlite" --exclude "*.sqlite3" --exclude "*.wallet"
  --exclude ".aws/*" --exclude "*/.aws/*"
  --exclude "PUBLIC_REVIEWED" --exclude "node_modules/*" --exclude "*/node_modules/*"
  --exclude "__pycache__/*" --exclude "*/__pycache__/*"
)

MODE=(--dryrun)
if [ "$APPLY" = "--apply" ]; then
  # Public uploads need a human to confirm the folder holds only sanitized files.
  if [ "$KIND" = "research" ] && [ ! -f "$SRC/PUBLIC_REVIEWED" ]; then
    echo "Refusing public upload: review the files, then create $SRC/PUBLIC_REVIEWED" >&2
    exit 1
  fi
  MODE=()
fi

echo "Source: $SRC"
echo "Dest:   $DEST"
[ ${#MODE[@]} -gt 0 ] && echo "Mode:   DRY RUN (add --apply to upload)" || echo "Mode:   UPLOAD"

aws s3 sync "$SRC" "$DEST" \
  --exclude "*" "${INC[@]}" "${SAFE_EXCLUDES[@]}" \
  --sse AES256 "${MODE[@]}"
