#!/usr/bin/env bash
set -exu

if test "$VIRTUAL_ENV" == ""; then
    echo No active virtualenv detected
    exit 1
fi

pip uninstall -y devpi-{common,client,server,web}
pip install -U --upgrade-strategy eager --no-use-pep517 -e common -e client -e server -e web PdbEditorSupport Sphinx pytest mock webtest pytest-cov pytest-flake8 "flake8<5" pytest-pdb pytest-timeout beautifulsoup4 execnet supervisor tox "towncrier>=21.9.0" wheel certauth
