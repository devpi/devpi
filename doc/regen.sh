#/bin/bash 
set -e -x -o nounset

export VENV_DIR=/tmp/docenv

[ -z "$PIP_INDEX_URL" ] && exit "need to set PIP_INDEX_URL to an index that contains the latest devpi packages because especially quickstart-server doc regeneration depends on it"

echo $(pwd)
echo $TMPDIR

rm -rf ${VENV_DIR} ${TMPDIR}/devpi*
virtualenv -p python3 -q ${VENV_DIR}
. ${VENV_DIR}/bin/activate
echo $VIRTUAL_ENV
echo $PATH
export VIRTUAL_ENV
export PATH

echo `which pip`

pip install -q -U build pip
echo devpi-server: `which devpi-server` $*

regendoc \
    --verbose \
    --normalize "/[ \t]+\n/\n/" \
    --normalize "@generated uuid: [0-9a-f]+@generated uuid: 446e22e0db5e41a5989fd671e98ec30b@" \
    --normalize "@\\\$PYTHON_PREFIX@/home/devpi/devpi@" \
    --normalize "@\\\$REGENDOC_TMPDIR@/home/devpi/devpi/doc@" \
    --normalize "@$TMPDIR@/tmp/@" \
    --normalize "@/private/home@/home@" \
    --normalize "@/private/tmp/docenv@/tmp/docenv@" \
    $*
