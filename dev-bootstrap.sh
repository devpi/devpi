#!/usr/bin/env bash
set -e

if test "$VIRTUAL_ENV" == ""; then
    echo No active virtualenv detected
    exit 1
fi

for i in common client server web ; do
    pip uninstall -y devpi-$i
done
for i in web server client common ; do
    (cd $i ; pip install -U -e .)
done

# install some deps for testing
pip install -U --upgrade-strategy eager PdbEditorSupport Sphinx pytest mock webtest pytest-cov pytest-flake8 pytest-pdb pytest-timeout beautifulsoup4 supervisor tox towncrier wheel certauth
