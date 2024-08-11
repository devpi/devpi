#!/bin/bash
set -e -o nounset
FORK_POINT=$(git merge-base origin/main HEAD)
FILES=$(git diff --relative --name-only $FORK_POINT -- '*.py')
RUFF_OUTPUT_CLIENT=$(ruff check --extend-exclude pytest-failed --config ruff-strict.toml --extend-ignore=I001 --exit-zero --output-format concise client)
RUFF_OUTPUT_COMMON=$(ruff check --extend-exclude pytest-failed --config ruff-strict.toml --extend-ignore=I001 --exit-zero --output-format concise common)
RUFF_OUTPUT_DEBUGGING=$(ruff check --extend-exclude pytest-failed --config ruff-strict.toml --extend-ignore=I001 --exit-zero --output-format concise debugging)
RUFF_OUTPUT_POSTGRESQL=$(ruff check --extend-exclude pytest-failed --config ruff-strict.toml --extend-ignore=I001 --exit-zero --output-format concise postgresql)
RUFF_OUTPUT_SERVER=$(ruff check --extend-exclude pytest-failed --config ruff-strict.toml --extend-ignore=I001 --exit-zero --output-format concise server)
RUFF_OUTPUT_WEB=$(ruff check --extend-exclude pytest-failed --config ruff-strict.toml --extend-ignore=I001 --exit-zero --output-format concise web)
RUFF_OUTPUT="$RUFF_OUTPUT_CLIENT\n$RUFF_OUTPUT_COMMON\n$RUFF_OUTPUT_DEBUGGING\n$RUFF_OUTPUT_POSTGRESQL\n$RUFF_OUTPUT_SERVER\n$RUFF_OUTPUT_WEB"
FLAKE8_OUTPUT_CLIENT=$(flake8 --ignore E501,E741,W503 client/ --exit-zero)
FLAKE8_OUTPUT_COMMON=$(flake8 --ignore E501,E741,W503 common/ --exit-zero)
FLAKE8_OUTPUT_DEBUGGING=$(flake8 --ignore E501,E741,W503 debugging/ --exit-zero)
FLAKE8_OUTPUT_POSTGRESQL=$(flake8 --ignore E501,E741,W503 postgresql/ --exit-zero)
FLAKE8_OUTPUT_SERVER=$(flake8 --ignore E501,E741,W503 server/ --exit-zero)
FLAKE8_OUTPUT_WEB=$(flake8 --ignore E501,E741,W503 web/ --exit-zero)
FLAKE8_OUTPUT="$FLAKE8_OUTPUT_CLIENT\n$FLAKE8_OUTPUT_COMMON\n$FLAKE8_OUTPUT_DEBUGGING\n$FLAKE8_OUTPUT_POSTGRESQL\n$FLAKE8_OUTPUT_SERVER\n$FLAKE8_OUTPUT_WEB"
match-diff-lines <(git diff --unified=0 --relative $FORK_POINT -- '*.py') <(echo "$RUFF_OUTPUT" "$FLAKE8_OUTPUT")

FLAKE8_UNUSED=""

FLAKE8_IGNORES_CLIENT="$(python .ci/flake8-ignores.py client)"
FLAKE8_UNUSED_CLIENT=""
for RULE in $FLAKE8_IGNORES_CLIENT; do grep -q $RULE <(echo "$FLAKE8_OUTPUT_CLIENT") || FLAKE8_UNUSED_CLIENT="$FLAKE8_UNUSED_CLIENT $RULE"; done
if test -n "$FLAKE8_UNUSED_CLIENT"; then echo "The following flake8 ignores for client no longer apply:$FLAKE8_UNUSED_CLIENT"; FLAKE8_UNUSED="$FLAKE8_UNUSED client"; fi

FLAKE8_IGNORES_COMMON="$(python .ci/flake8-ignores.py common)"
FLAKE8_UNUSED_COMMON=""
for RULE in $FLAKE8_IGNORES_COMMON; do grep -q $RULE <(echo "$FLAKE8_OUTPUT_COMMON") || FLAKE8_UNUSED_COMMON="$FLAKE8_UNUSED_COMMON $RULE"; done
if test -n "$FLAKE8_UNUSED_COMMON"; then echo "The following flake8 ignores for common no longer apply:$FLAKE8_UNUSED_COMMON"; FLAKE8_UNUSED="$FLAKE8_UNUSED common"; fi

FLAKE8_IGNORES_DEBUGGING="$(python .ci/flake8-ignores.py debugging)"
FLAKE8_UNUSED_DEBUGGING=""
for RULE in $FLAKE8_IGNORES_DEBUGGING; do grep -q $RULE <(echo "$FLAKE8_OUTPUT_DEBUGGING") || FLAKE8_UNUSED_DEBUGGING="$FLAKE8_UNUSED_DEBUGGING $RULE"; done
if test -n "$FLAKE8_UNUSED_DEBUGGING"; then echo "The following flake8 ignores for debugging no longer apply:$FLAKE8_UNUSED_DEBUGGING"; FLAKE8_UNUSED="$FLAKE8_UNUSED debugging"; fi

FLAKE8_IGNORES_POSTGRESQL="$(python .ci/flake8-ignores.py postgresql)"
FLAKE8_UNUSED_POSTGRESQL=""
for RULE in $FLAKE8_IGNORES_POSTGRESQL; do grep -q $RULE <(echo "$FLAKE8_OUTPUT_POSTGRESQL") || FLAKE8_UNUSED_POSTGRESQL="$FLAKE8_UNUSED_POSTGRESQL $RULE"; done
if test -n "$FLAKE8_UNUSED_POSTGRESQL"; then echo "The following flake8 ignores for postgresql no longer apply:$FLAKE8_UNUSED_POSTGRESQL"; FLAKE8_UNUSED="$FLAKE8_UNUSED postgresql"; fi

FLAKE8_IGNORES_SERVER="$(python .ci/flake8-ignores.py server)"
FLAKE8_UNUSED_SERVER=""
for RULE in $FLAKE8_IGNORES_SERVER; do grep -q $RULE <(echo "$FLAKE8_OUTPUT_SERVER") || FLAKE8_UNUSED_SERVER="$FLAKE8_UNUSED_SERVER $RULE"; done
if test -n "$FLAKE8_UNUSED_SERVER"; then echo "The following flake8 ignores for server no longer apply:$FLAKE8_UNUSED_SERVER"; FLAKE8_UNUSED="$FLAKE8_UNUSED server"; fi

FLAKE8_IGNORES_WEB="$(python .ci/flake8-ignores.py web)"
FLAKE8_UNUSED_WEB=""
for RULE in $FLAKE8_IGNORES_WEB; do grep -q $RULE <(echo "$FLAKE8_OUTPUT_WEB") || FLAKE8_UNUSED_WEB="$FLAKE8_UNUSED_WEB $RULE"; done
if test -n "$FLAKE8_UNUSED_WEB"; then echo "The following flake8 ignores for web no longer apply:$FLAKE8_UNUSED_WEB"; FLAKE8_UNUSED="$FLAKE8_UNUSED web"; fi

RUFF_UNUSED=""

RUFF_IGNORES_CLIENT="$(python .ci/ruff-ignores.py client)"
RUFF_UNUSED_CLIENT=""
for RULE in $RUFF_IGNORES_CLIENT; do grep -q $RULE <(echo "$RUFF_OUTPUT_CLIENT") || RUFF_UNUSED_CLIENT="$RUFF_UNUSED_CLIENT $RULE"; done
if test -n "$RUFF_UNUSED_CLIENT"; then echo "The following ruff ignores for client no longer apply:$RUFF_UNUSED_CLIENT"; RUFF_UNUSED="$RUFF_UNUSED client"; fi

RUFF_IGNORES_COMMON="$(python .ci/ruff-ignores.py common)"
RUFF_UNUSED_COMMON=""
for RULE in $RUFF_IGNORES_COMMON; do grep -q $RULE <(echo "$RUFF_OUTPUT_COMMON") || RUFF_UNUSED_COMMON="$RUFF_UNUSED_COMMON $RULE"; done
if test -n "$RUFF_UNUSED_COMMON"; then echo "The following ruff ignores for common no longer apply:$RUFF_UNUSED_COMMON"; RUFF_UNUSED="$RUFF_UNUSED common"; fi

RUFF_IGNORES_DEBUGGING="$(python .ci/ruff-ignores.py debugging)"
RUFF_UNUSED_DEBUGGING=""
for RULE in $RUFF_IGNORES_DEBUGGING; do grep -q $RULE <(echo "$RUFF_OUTPUT_DEBUGGING") || RUFF_UNUSED_DEBUGGING="$RUFF_UNUSED_DEBUGGING $RULE"; done
if test -n "$RUFF_UNUSED_DEBUGGING"; then echo "The following ruff ignores for debugging no longer apply:$RUFF_UNUSED_DEBUGGING"; RUFF_UNUSED="$RUFF_UNUSED debugging"; fi

RUFF_IGNORES_POSTGRESQL="$(python .ci/ruff-ignores.py postgresql)"
RUFF_UNUSED_POSTGRESQL=""
for RULE in $RUFF_IGNORES_POSTGRESQL; do grep -q $RULE <(echo "$RUFF_OUTPUT_POSTGRESQL") || RUFF_UNUSED_POSTGRESQL="$RUFF_UNUSED_POSTGRESQL $RULE"; done
if test -n "$RUFF_UNUSED_POSTGRESQL"; then echo "The following ruff ignores for postgresql no longer apply:$RUFF_UNUSED_POSTGRESQL"; RUFF_UNUSED="$RUFF_UNUSED postgresql"; fi

RUFF_IGNORES_SERVER="$(python .ci/ruff-ignores.py server)"
RUFF_UNUSED_SERVER=""
for RULE in $RUFF_IGNORES_SERVER; do grep -q $RULE <(echo "$RUFF_OUTPUT_SERVER") || RUFF_UNUSED_SERVER="$RUFF_UNUSED_SERVER $RULE"; done
if test -n "$RUFF_UNUSED_SERVER"; then echo "The following ruff ignores for server no longer apply:$RUFF_UNUSED_SERVER"; RUFF_UNUSED="$RUFF_UNUSED server"; fi

RUFF_IGNORES_WEB="$(python .ci/ruff-ignores.py web)"
RUFF_UNUSED_WEB=""
for RULE in $RUFF_IGNORES_WEB; do grep -q $RULE <(echo "$RUFF_OUTPUT_WEB") || RUFF_UNUSED_WEB="$RUFF_UNUSED_WEB $RULE"; done
if test -n "$RUFF_UNUSED_WEB"; then echo "The following ruff ignores for web no longer apply:$RUFF_UNUSED_WEB"; RUFF_UNUSED="$RUFF_UNUSED web"; fi

if test -n "$FLAKE8_UNUSED$RUFF_UNUSED"; then exit 1; fi
