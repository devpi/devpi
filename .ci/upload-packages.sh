#!/bin/bash
set -xe -o nounset
yes yes | devpi index --delete "${DEVPI_INDEXNAME}" || true
devpi index -c "${DEVPI_INDEXNAME}" bases=root/pypi
devpi use "${DEVPI_INDEXNAME}"
# for devpi-server 5.x
devpi push --index root/pypi devpi-common==3.7.2 "${DEVPI_INDEXNAME}"
# contains py.typed marker
devpi push --index root/pypi devpi-common==4.1.0 "${DEVPI_INDEXNAME}"
devpi push --index root/pypi devpi-server==5.2.0 "${DEVPI_INDEXNAME}"
devpi push --index root/pypi devpi-server==6.8.0 "${DEVPI_INDEXNAME}"
# contains py.typed marker
devpi push --index root/pypi devpi-server==6.15.0 "${DEVPI_INDEXNAME}"
pushd common
python -m pip install .
towncrier build --yes || true
head -n 50 CHANGELOG
devpi upload --no-isolation
popd
pushd server
python -m pip install .
towncrier build --yes || true
head -n 50 CHANGELOG
devpi upload --no-isolation
popd
pushd web
python -m pip install .
towncrier build --yes || true
head -n 50 CHANGELOG
devpi upload --no-isolation
popd
pushd client
python -m pip install .
towncrier build --yes || true
head -n 50 CHANGELOG
devpi upload --no-isolation
popd
pushd postgresql
python -m pip install .
towncrier build --yes || true
head -n 50 CHANGELOG
devpi upload --no-isolation
popd
