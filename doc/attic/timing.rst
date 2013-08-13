
Example timing
--------------

Here is a little screen session when using a fresh ``devpi-server``
instance, installing itself in a fresh virtualenv::

    hpk@teta:~/p/devpi-server$ virtualenv devpi >/dev/null
    hpk@teta:~/p/devpi-server$ source devpi/bin/activate
    (devpi) hpk@teta:~/p/devpi-server$ time pip install -q \
                -i https://pypi.python.org/simple/ django-treebeard

    real  15.871s
    user   3.884s
    system 2.684s

So that took around 15 seconds.  Now lets remove the virtualenv, recreate
it and install ``django-treebeard`` again, now using devpi-server::

    (devpi) hpk@teta:~/p/devpi-server$ rm -rf devpi
    (devpi) hpk@teta:~/p/devpi-server$ virtualenv devpi  >/dev/null
    (devpi)hpk@teta:~/p/devpi-server$ time pip install -q -i http://localhost:3141/root/pypi/+simple/ django-treebeard

    real   6.219s
    user   3.912s
    system 2.716s

So it's around 2-3 times faster on a 30Mbit internet connection.

