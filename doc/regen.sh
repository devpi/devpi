#/bin/bash 

export DEVPI_CLIENTDIR=/tmp/home/.devpi/client
export DEVPI_SERVERDIR=/tmp/home/.devpi/server
export VENV_DIR=/tmp/docenv

alias devpi-server=`which devpi-server`
alias devpi=`which devpi`

[ -z "$PIP_INDEX_URL" ] && exit "need to set PIP_INDEX_URL"

rm -rf ${VENV_DIR} TARGETDIR docenv v1 ${DEVPI_SERVERDIR} ${DEVPI_CLIENTDIR} ${TMPDIR}/devpi*
virtualenv -q ${VENV_DIR}
. ${VENV_DIR}/bin/activate
echo $PATH

pip install -q py
#echo `which python` `which devpi-server` $*

python regendoc.py $*
