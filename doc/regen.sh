#/bin/bash 

export DEVPI_CLIENTDIR=/tmp/home/.devpi/client
export DEVPI_SERVERDIR=/tmp/home/.devpi/server
export VENV_DIR=/tmp/docenv

alias devpi-server=`which devpi-server`
alias devpi=`which devpi`

[ -z "$PIP_INDEX_URL" ] && exit "need to set PIP_INDEX_URL to an index that contains the latest devpi packages because especially quickstart-server doc regeneration depends on it"

rm -rf ${VENV_DIR} TARGETDIR docenv v1 ${DEVPI_SERVERDIR} ${DEVPI_CLIENTDIR} ${TMPDIR}/devpi*
virtualenv -q ${VENV_DIR}
. ${VENV_DIR}/bin/activate
echo $PATH

pip install -q py
echo devpi-server: `which devpi-server` $*

python regendoc.py $*
