XXX The devpi-server REST HTTP API
==================================

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
      "status": 201, 
      "type": "userconfig", 
      "result": {
        "username": "alice", 
        "email": "alice@example.com"
      }
    }

Create an ``alice/dev`` index inheriting directly from ``root/pypi``,
using the just created "alice" credentials::

    $ curl -H "Accept: application/json" -H "Content-Type: application/json" \
           --user alice:123 -s -d '{"bases": ["root/pypi"]}' \
           -X PUT http://localhost:3141/alice/dev
    {
      "status": 201, 
      "type": "indexconfig", 
      "result": {
        "type": "stage", 
        "bases": [
          "root/pypi"
        ], 
        "volatile": true
      }
    }

Registering an ``example`` project in the new ``alice/dev`` index::

     $ curl -H "Accept: application/json" -H "Content-Type: application/json"  \
           --user alice:123 -s  \
           -X PUT http://localhost:3141/alice/dev/example
     {
       "status": 201, 
       "message": "project 'example' created"
     }

Looking at list of projects in ``alice/dev`` index::

     $ curl -H "Accept: application/json" -s \
           -X GET http://localhost:3141/alice/dev/
     {
       "status": 200,
       "type": "list:projectconfig",
       "result": [
         "example"
       ]
     }

The project list supports several optional query parameters:

``?q=<substring>``
    Filter project names by substring match::

        $ curl -H "Accept: application/json" -s \
              http://localhost:3141/root/pypi?q=flask
        {
          "result": {"projects": ["flask", "flask-login", "flask-wtf"]}
        }

``?total=1``
    Include the total count of (filtered) projects in the response::

        $ curl -H "Accept: application/json" -s \
              "http://localhost:3141/root/pypi?q=flask&total=1"
        {
          "result": {"projects": ["flask", "flask-login"], "total": 2}
        }

``?cached=1``
    Include a ``cached`` list — projects that have locally cached metadata
    (mirror indexes only)::

        $ curl -H "Accept: application/json" -s \
              http://localhost:3141/root/pypi?cached=1
        {
          "result": {
            "projects": ["flask", "django", "requests"],
            "cached": ["flask"]
          }
        }

``?limit=<n>&offset=<n>``
    Paginate the project list. When ``limit`` is present, ``offset`` and
    ``limit`` are included in the response. ``offset`` defaults to 0::

        $ curl -H "Accept: application/json" -s \
              "http://localhost:3141/root/pypi?limit=2&offset=0"
        {
          "result": {
            "projects": ["aiohttp", "attrs"],
            "limit": 2,
            "offset": 0
          }
        }

All parameters can be combined freely::

    $ curl -H "Accept: application/json" -s \
          "http://localhost:3141/root/pypi?q=flask&cached=1&total=1&limit=10&offset=0"
    {
      "result": {
        "projects": ["flask", "flask-login", "flask-wtf"],
        "cached": ["flask"],
        "total": 3,
        "limit": 10,
        "offset": 0
      }
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

Getting index or user information
--------------------------------------------------

Getting index configuration::

    $ curl --user alice:123 -s -X GET http://localhost:3141/alice/dev
    {
      "status": 200, 
      "type": "indexconfig", 
      "result": {
        "volatile": true, 
        "bases": [
          "root/pypi"
        ], 
        "type": "stage"
      }
    }

Getting user information::

    $ curl --user alice:123 -s -X GET http://localhost:3141/alice
    {
      "status": 200, 
      "type": "userconfig", 
      "result": {
        "username": "alice", 
        "email": "alice@example.com", 
        "indexes": {
          "dev": {
            "volatile": true, 
            "bases": [
              "root/pypi"
            ], 
            "type": "stage"
          }
        }
      }
    }

Getting all users and indexes::

    $ curl --user alice:123 -s -X GET http://localhost:3141/
    {
      "status": 200, 
      "type": "list:userconfig", 
      "result": {
        "hpk": {
          "username": "hpk", 
          "email": "qwe", 
          "indexes": {
            "dev": {
              "type": "stage", 
              "bases": [
                "root/dev"
              ], 
              "volatile": true
            }
          }
        }, 
        "root": {
          "username": "root", 
          "indexes": {
            "pypi": {
              "volatile": false, 
              "bases": [], 
              "type": "mirror"
            }, 
            "dev": {
              "type": "stage", 
              "bases": [
                "root/pypi"
              ], 
              "volatile": true
            }
          }
        }, 
        "alice": {
          "username": "alice", 
          "email": "alice@example.com", 
          "indexes": {
            "dev": {
              "volatile": true, 
              "bases": [
                "root/pypi"
              ], 
              "type": "stage"
            }
          }
        }
      }
    }

Deleting an index or user
--------------------------------------------------

Deleting an index::

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
