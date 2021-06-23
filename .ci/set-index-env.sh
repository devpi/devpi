#!/bin/bash
set -xe -o nounset
export GITHUB_BRANCH_NAME="${GITHUB_REF##*/}"
export DEVPI_INDEX="devpi-github/${GITHUB_REPOSITORY/\//-}-${GITHUB_BRANCH_NAME/\//-}"
export PIP_INDEX_URL="https://m.devpi.net/${DEVPI_INDEX}/+simple/"
