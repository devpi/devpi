#/bin/bash 

export DEVPI_CLIENTDIR=/tmp/home/.devpi/client
export DEVPI_SERVERDIR=/tmp/home/.devpi/server
export VENV_DIR=/tmp/docenv

rm -rf ${VENV_DIR} TARGETDIR docenv v1 ${DEVPI_SERVERDIR} ${DEVPI_CLIENTDIR} ${TMPDIR}/devpi*
virtualenv -q ${VENV_DIR}
. ${VENV_DIR}/bin/activate
pip install -q py
python regendoc.py $*
rm -rf docenv
