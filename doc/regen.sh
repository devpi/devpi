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

pip install -U build pip
echo devpi-server: `which devpi-server` $*

regendoc \
    --verbose \
    --normalize "/[ \t]+\n/\n/" \
    --normalize "@Waiting for (.+:3141) \.+@Waiting for \1@" \
    --normalize "@generated uuid: [0-9a-f]+@generated uuid: 446e22e0db5e41a5989fd671e98ec30b@" \
    --normalize "@\\\$PYTHON_PREFIX@/home/devpi/devpi@" \
    --normalize "@\\\$REGENDOC_TMPDIR@/home/devpi/devpi/doc@" \
    --normalize "@$TMPDIR@/tmp/@" \
    --normalize "@/home/.+/etc/supervisor-devpi.conf@/home/testuser/etc/supervisor-devpi.conf@" \
    --normalize "@/private/home@/home@" \
    --normalize "@/private/tmp@/tmp@" \
    --normalize "@/tmp/devpi-test-[a-z0-9_]+\b@/tmp/devpi-test0@" \
    --normalize "@/tmp/devpi(?!-test)-[a-z0-9_]+\b@/tmp/devpi0@" \
    --normalize "@python3\.\d+@python3.8@" \
    --normalize "@Python 3\.\d+\.\d+@Python 3.8.12@" \
    --normalize "@platform .+ --@platform linux --@" \
    --normalize "@/[0-9a-f]{3}/[0-9a-f]{13}/example-1.0.tar.gz@/853/34ff3d48c83ba/example-1.0.tar.gz@" \
    --normalize "@/[0-9a-f]{3}/[0-9a-f]{13}/example-1.0-py3-none-any.whl@/0b1/6414c21b576b1/example-1.0-py3-none-any.whl@" \
    --normalize "@/[0-9a-f]{3}/[0-9a-f]{13}/pysober-0.1.0.tar.gz@/7e7/cd189c623c62f/pysober-0.1.0.tar.gz@" \
    --normalize "@/[0-9a-f]{3}/[0-9a-f]{13}/pysober-0.1.0-py3-none-any.whl@/c44/077f25603b307/pysober-0.1.0-py3-none-any.whl@" \
    --normalize "@/[0-9a-f]{3}/[0-9a-f]{13}/pysober-0.2.0.tar.gz@/1f9/4765a5f4ad388/pysober-0.2.0.tar.gz@" \
    --normalize "@/[0-9a-f]{3}/[0-9a-f]{13}/pysober-0.2.0-py3-none-any.whl@/746/cbe664b96ffc1/pysober-0.2.0-py3-none-any.whl@" \
    --normalize "@/[0-9a-f]{3}/[0-9a-f]{13}/pysober-0.2.1.tar.gz@/71c/1ac419167f9a7/pysober-0.2.1.tar.gz@" \
    --normalize "@/[0-9a-f]{3}/[0-9a-f]{13}/pysober-0.2.1-py3-none-any.whl@/746/cbe664b96ffc1/pysober-0.2.1-py3-none-any.whl@" \
    --normalize "@pysober-0\.(\d\.\d).tar.gz \d+kb@pysober-0.\1.tar.gz 3kb@" \
    --normalize "@\.toxresult-\d{14}-0@.toxresult-20210510144323-0@" \
    --normalize "@\"created\": \"20\d{2}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z\"@\"created\": \"2021-05-10T14:44:15Z\"@" \
    --normalize "@\"modified\": \"20\d{2}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z\"@\"created\": \"2021-05-10T14:44:18Z\"@" \
    --normalize '@= 1 passed in \d+\.\d+s =@= 1 passed in 0.01s =@' \
    --normalize "@py: OK \(\d+\.\d+ seconds\)@py: OK (10.57 seconds)@" \
    --normalize "@congratulations :\) \(\d+\.\d+ seconds\)@congratulations :) (10.85 seconds)@" \
    $*
