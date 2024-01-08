#!/bin/sh
set -exu

if test "$VIRTUAL_ENV" == ""; then
    echo No active virtualenv detected
    exit 1
fi

pip uninstall -y devpi-{common,client,server,web}
pip install -U --upgrade-strategy eager --no-use-pep517 -r dev-requirements.txt
