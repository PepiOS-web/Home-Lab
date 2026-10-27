#!/usr/bin/env bash
# Non-publishing, non-installing parser regression tests. No root required.
set -euo pipefail
root=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
source "$root/homelab-update"

plan=$(printf '%s\n' \
    'Inst tzdata [2026c-0ubuntu0.24.04.1] (2026e-0ubuntu0.24.04.1 Ubuntu:24.04/noble-updates [all])' \
    'Inst docker-ce [5:29.8.1-1~ubuntu.24.04~noble] (5:29.9.1-1~ubuntu.24.04~noble Docker CE:noble [amd64])' \
    'Inst tailscale [1.102.4] (1.104.1 Tailscale:pkgs.tailscale.com [amd64])' | classify_plan)
[[ "$plan" == $'ubuntu\ttzdata=2026e-0ubuntu0.24.04.1\ndocker\tdocker-ce=5:29.9.1-1~ubuntu.24.04~noble\ntailscale\ttailscale=1.104.1' ]]
for invalid in 'Remv important-package [1.0]' 'Inst malformed unexpected' 'Inst example [1] (bad;command Ubuntu [all])'; do
    if printf '%s\n' "$invalid" | classify_plan >/dev/null 2>&1; then
        printf '%s\n' 'FAIL: invalid plan accepted' >&2; exit 1
    fi
done
[[ -z $(printf '%s\n' '0 upgraded, 0 newly installed, 0 to remove and 3 not upgraded.' | classify_plan) ]]
printf '%s\n' 'PASS: groups, exact versions, empty plan, removals and malformed entries'
