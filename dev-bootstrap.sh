#!/usr/bin/env bash
set -exu

if test "$VIRTUAL_ENV" == ""; then
    echo No active virtualenv detected
    exit 1
fi

pip uninstall -y devpi-{common,client,server,web}
pip install -U --upgrade-strategy eager -e common -e client -e server -e web PdbEditorSupport Sphinx pytest mock webtest pytest-cov pytest-flake8 pytest-pdb pytest-timeout beautifulsoup4 supervisor tox "towncrier>=21.9.0" wheel certauth
