
.. 
    $ devpi logoff
    login information deleted

Using the http://devpi.net server::

    $ devpi use http://devpi.net
    connected to: http://devpi.net/ (logged in as test)
    not using any index ('index -l' to discover, then 'use NAME' to use one)
    no current install venv set

Registering a user with a password (not specifying the password will ask
it interactively)::

    $ devpi user -c user1 password=pass1
    user created: user1

Logging in as that user::

    $ devpi login user1 --password=pass1
    logged in 'user1', credentials valid for 10.00 hours

Creating an index for that user:

    $ devpi index -c dev
    dev:
      type=stage
      bases=root/dev
      volatile=True
      uploadtrigger_jenkins=None
      acl_upload=

Using that index:

    $ devpi use user1/dev
    using index: http://devpi.net/user1/dev/ (logged in as user1)
    no current install venv set

...

Deleting the user:

    $ devpi user --delete user1
    user deleted: user1

(logging off -- it should already happen when deleting the user i guess)::

    $ devpi logoff
    login information deleted
