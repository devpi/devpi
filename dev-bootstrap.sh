#!/bin/sh
set -exu

if test "$VIRTUAL_ENV" == ""; then
    echo No active virtualenv detected
    exit 1
fi

if which uv; then
    UNINSTALL_COMMAND="uv pip uninstall"
    INSTALL_COMMAND="uv pip install --reinstall --config-setting editable_mode=compat"
else
    UNINSTALL_COMMAND="pip uninstall -y"
    INSTALL_COMMAND="pip install --upgrade-strategy eager"
fi

$UNINSTALL_COMMAND devpi-{common,client,server,web}
$INSTALL_COMMAND -U -r dev-requirements.txt
