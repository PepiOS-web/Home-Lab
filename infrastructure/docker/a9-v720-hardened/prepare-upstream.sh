#!/usr/bin/env bash
set -euo pipefail

commit='a795f8b4e17a03394d66cdde1d2633dd08e6be87'
expected_sha256='61b794b36c8dfdfeb8ae81de5cbce5ea6cc433a9512ffb07edcd9567a112774e'
project_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
work_dir="$(mktemp -d)"
archive="$work_dir/upstream.zip"
extracted="$work_dir/extracted"
target="$project_dir/_upstream"

cleanup() {
  rm -rf -- "$work_dir"
}
trap cleanup EXIT

curl --fail --location --proto '=https' --tlsv1.2 \
  "https://github.com/intx82/a9-v720/archive/${commit}.zip" \
  --output "$archive"

printf '%s  %s\n' "$expected_sha256" "$archive" | sha256sum --check --strict

mkdir -p "$extracted" "$target"
unzip -q "$archive" "a9-v720-${commit}/src/*" -d "$extracted"
rm -rf -- "$target"
mkdir -p "$target"
cp -a "$extracted/a9-v720-${commit}/src" "$target/src"

git -C "$target" apply --check "$project_dir/upstream.patch"
git -C "$target" apply "$project_dir/upstream.patch"

python3 -m py_compile \
  "$target/src/v720_http.py" \
  "$target/src/v720_sta.py" \
  "$target/src/hardened_server.py"

echo "Prepared audited a9-v720 source at $target"
