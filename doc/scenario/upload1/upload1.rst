
..
    $ devpi use http://devpi.net
    connected to: http://devpi.net/ (logged in as user1)
    not using any index ('index -l' to discover, then 'use NAME' to use one)
    no current install venv set

..
    $ devpi user -c test password=test
    PUT http://devpi.net/test
    409 Conflict: user already exists

..
    $ devpi login test --password test
    logged in 'test', credentials valid for 10.00 hours

..
    $ devpi index -c dev
    PUT http://devpi.net/test/dev
    409 Conflict: index test/dev exists

..
    $ devpi use test/dev
    using index: http://devpi.net/test/dev/ (logged in as test)
    no current install venv set

Login as a test user::

    $ devpi login test password=test
    /home/hpk/bin/devpi: error: unrecognized arguments: password=test
    usage: /home/hpk/bin/devpi [-h] [--version] [--debug] [-y] [--clientdir DIR]
                               
                               {use,getjson,list,remove,user,login,logoff,index,upload,test,push,install,server}
                               ...

Use a dev index::

    $ devpi use http://devpi.net/test/dev/
    using index: http://devpi.net/test/dev/ (logged in as test)
    no current install venv set

Upload a package (requires a logged in user using his own index)::

    $ devpi upload
    created workdir /tmp/devpi1002
    --> $ hg st -nmac .
    hg-exported project to <Exported /tmp/devpi1002/upload/upload1>
    --> $ /home/hpk/venv/0/bin/python /home/hpk/p/devpi/client/devpi/upload/setuppy.py /tmp/devpi1002/upload/upload1 http://devpi.net/test/dev/ test test-dd85d93865f08ff2706ba12b38c4a894c807ecdfd56f105928b2c27a1d0805b8.BOjF5A.iSCJquHUUBjsxBVVh_F2RBIe-_k register -r devpi
    warning: check: missing required meta-data: url
    
    --> $ /home/hpk/venv/0/bin/python /tmp/devpi1002/upload/upload1/setup.py --fullname
    got local pypi-fullname example-1.0
    release registered example-1.0
    --> $ /home/hpk/venv/0/bin/python /home/hpk/p/devpi/client/devpi/upload/setuppy.py /tmp/devpi1002/upload/upload1 http://devpi.net/test/dev/ test test-dd85d93865f08ff2706ba12b38c4a894c807ecdfd56f105928b2c27a1d0805b8.BOjF5A.iSCJquHUUBjsxBVVh_F2RBIe-_k sdist --formats gztar upload -r devpi
    warning: sdist: standard file not found: should have one of README, README.rst, README.txt
    
    warning: check: missing required meta-data: url
    
    submitted dist/example-1.0.tar.gz to http://devpi.net/test/dev/

Check what we uploaded::

    $ devpi list example
    test/dev/example/1.0/example-1.0.tar.gz

Run tests via tox::

    $ devpi test example
    received http://devpi.net/test/dev/example/1.0/example-1.0.tar.gz
    verified md5 ok 21d7e7adb5cb2a9757d66ce223214782
    unpacking /tmp/devpi-test200/downloads/example-1.0.tar.gz to /tmp/devpi-test200
    /tmp/devpi-test200/example-1.0$ /home/hpk/venv/0/bin/tox --installpkg /tmp/devpi-test200/downloads/example-1.0.tar.gz -i ALL=http://devpi.net/test/dev/+simple/ --result-json /tmp/devpi-test200/toxreport.json -v
    using tox.ini: /tmp/devpi-test200/example-1.0/tox.ini
    using tox-1.6.0.dev4 from /home/hpk/p/tox/tox/__init__.pyc
    python create: /tmp/devpi-test200/example-1.0/.tox/python
      /tmp/devpi-test200/example-1.0/.tox$ /home/hpk/venv/0/bin/python /home/hpk/venv/0/local/lib/python2.7/site-packages/virtualenv.py --setuptools --python /home/hpk/venv/0/bin/python python >/tmp/devpi-test200/example-1.0/.tox/python/log/python-0.log
    python inst: /tmp/devpi-test200/downloads/example-1.0.tar.gz
      /tmp/devpi-test200/example-1.0/.tox/python/log$ /tmp/devpi-test200/example-1.0/.tox/python/bin/pip install -i http://devpi.net/test/dev/+simple/ /tmp/devpi-test200/downloads/example-1.0.tar.gz >/tmp/devpi-test200/example-1.0/.tox/python/log/python-1.log
    python runtests: commands[0] | python -c import example ; assert example.hello() == "world"
      /tmp/devpi-test200/example-1.0$ /tmp/devpi-test200/example-1.0/.tox/python/bin/python -c import example ; assert example.hello() == "world" >/tmp/devpi-test200/example-1.0/.tox/python/log/python-2.log
    ___________________________________ summary ____________________________________
      python: commands succeeded
      congratulations :)
    wrote json report at: /tmp/devpi-test200/toxreport.json
    posting tox result data to http://devpi.net/+tests
    successfully posted tox result data
  
check about file status again::

    $ devpi list example
    test/dev/example/1.0/example-1.0.tar.gz
      teta linux2 python 2.7.3 tests passed

..
    devpi user --delete test 
