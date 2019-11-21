#/bin/bash 

export VENV_DIR=/tmp/docenv

alias devpi-server=`which devpi-server`
alias devpi=`which devpi`

[ -z "$PIP_INDEX_URL" ] && exit "need to set PIP_INDEX_URL to an index that contains the latest devpi packages because especially quickstart-server doc regeneration depends on it"

rm -rf ${VENV_DIR} TARGETDIR docenv v1 ${TMPDIR}/devpi*
virtualenv -q ${VENV_DIR}
. ${VENV_DIR}/bin/activate
echo $PATH

pip install -q py
echo devpi-server: `which devpi-server` $*

regendoc \
    --verbose \
    --normalize "/[ \t]+\n/\n/" \
    --normalize "@\\\$PYTHON_PREFIX@/home/devpi/devpi@" \
    --normalize "@\\\$REGENDOC_TMPDIR@/home/devpi/devpi/doc@" \
    --normalize "@\\\/private/home@/home@" \
    $*
