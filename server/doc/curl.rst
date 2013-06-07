The REST HTTP API
=======================

We demonstrate the devpi-server ReST API using curl interactively.
You can issue the same commands with a ``devpi-server`` process
running with defaults.


Creating a user, index, project and release file
--------------------------------------------------

Creating a user::

    $ curl -H "Accept: application/json" -H "Content-Type: application/json" \
           -d '{"password": "123", "email": "alice@example.com"}' -s \
           -X PUT http://localhost:3141/alice
    {
      "status": 409, 
      "message": "user already exists"
    }

Creating an ``alice/dev`` index inheriting directly from `root/pypi`_,
using using the just created "alice" credentials::

    $ curl -H "Accept: application/json" -H "Content-Type: application/json" \
           --user alice:123 -s -d '{"bases": ["root/pypi"]}' \
           -X PUT http://localhost:3141/alice/dev
    {
      "status": 409, 
      "message": "index alice/dev exists"
    }

Registering an ``example`` project in the new ``alice/dev`` index::

     $ curl -H "Accept: application/json" -H "Content-Type: application/json"  \
           --user alice:123 -s  \
           -X PUT http://localhost:3141/alice/dev/example
     {
       "status": 409, 
       "message": "project 'example' exists"
     }

Looking at list of projects in ``alice/dev`` index::

     $ curl -H "Accept: application/json" -s \
           -X GET http://localhost:3141/alice/dev/
     {
       "status": 200, 
       "result": [
         "example"
       ]
     }

Registering release files and docs (Unimplemented)
-----------------------------------------------------------------

Uploading an release file for the ``example`` project::

     curl -H "Accept: application/json" 
           --user alice:123 -s  \
           --data-binary @example-1.0.tar.gz
           -X PUT http://localhost:3141/alice/dev/example/1.0/example-1.0.tar.gz

Uploading documentation for a particular version::

     curl -H "Accept: application/json" 
           --user alice:123 -s  \
           --data-binary @doc.zip -X PUT \
           http://localhost:3141/alice/dev/example/1.0/example-1.0-doc.zip

Listing all files for ``example`` project, indexed by version::

      curl -H "Accept: application/json" -s \
           -X GET http://localhost:3141/alice/dev/example

Deleting files belonging to a particular version::

      curl -H "Accept: application/json" -s \
           -X DELETE http://localhost:3141/alice/dev/example/1.0

Deleting a project::

      curl -H "Accept: application/json" -s \
           -X DELETE http://localhost:3141/alice/dev/example/


Deleting an index or user
--------------------------------------------------

Deleting an index:

    $ curl --user alice:123 -s -X DELETE http://localhost:3141/alice/dev
    {
      "status": 201, 
      "message": "index alice/dev deleted"
    }

Deleting a user::

    $ curl --user alice:123 -s -X DELETE http://localhost:3141/alice
    {
      "status": 200, 
      "message": "user 'alice' deleted"
    }
