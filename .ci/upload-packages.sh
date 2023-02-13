#!/bin/bash
set -xe -o nounset
yes yes | devpi index --delete "${DEVPI_INDEXNAME}" || true
devpi index -c "${DEVPI_INDEXNAME}" bases=root/pypi
devpi use "${DEVPI_INDEXNAME}"
devpi push --index root/pypi devpi-server==5.2.0 "${DEVPI_INDEXNAME}"
devpi push --index root/pypi devpi-server==6.8.0 "${DEVPI_INDEXNAME}"
pushd common
yes | towncrier || true
devpi upload --no-isolation
popd
pushd server
yes | towncrier || true
devpi upload --no-isolation
popd
pushd web
yes | towncrier || true
devpi upload --no-isolation
popd
pushd client
yes | towncrier || true
devpi upload --no-isolation
popd
pushd postgresql
yes | towncrier || true
devpi upload --no-isolation
popd
