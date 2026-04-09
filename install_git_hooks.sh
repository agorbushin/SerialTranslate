#!/usr/bin/env bash
# One-time: use tracked hooks from .githooks/ (post-merge, post-checkout → restart bot when code changes).
set -euo pipefail
cd "$(dirname "$0")"
git config core.hooksPath .githooks
echo "Set core.hooksPath=.githooks for this repo."
