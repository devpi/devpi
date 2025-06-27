#!/bin/bash
set -eu -o nounset -o pipefail
exec .ci/lint_strict.py
