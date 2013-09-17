

LOC=`pwd`/env.testupgrade
rm -rf $LOC
virtualenv $LOC
export PATH=$LOC/bin:$PATH

pip install devpi-server==1.0 devpi-client==1.0

export DEVPI_SERVERDIR=$LOC/data

devpi-server --start --port 3999  || exit 1

pip install -q -i http://localhost:3999/root/pypi/+simple/ something 
pip install -i http://localhost:3999/root/pypi/+simple/ pytest-pep8 || exit 1
pip install -i http://localhost:3999/root/pypi/+simple/ pytest_pep8 

devpi use http://localhost:3999
devpi user -c user password=123
devpi login user --password=123
devpi index -c dev
devpi use user/dev
devpi upload

devpi-server --stop  

pip install -U 'devpi-server>=1.1.dev2'

devpi-server --export $LOC/export

export DEVPI_SERVERDIR=$LOC/data2
devpi-server --import $LOC/export

devpi-server --start --port 3999  || exit 1

devpi-server --stop  
devpi-server --log 

