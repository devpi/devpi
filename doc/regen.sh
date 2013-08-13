#/bin/bash 

export DEVPI_CLIENTDIR=`pwd`/.devpi/client
export DEVPI_SERVERDIR=`pwd`/.devpi/server

rm -rf docenv v1 ${DEVPI_SERVERDIR} ${DEVPI_CLIENTDIR}
virtualenv -q docenv 
. docenv/bin/activate
pip install -q py
python regendoc.py $*
rm -rf docenv
