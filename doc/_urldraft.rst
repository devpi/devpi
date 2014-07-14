
current URL API scheme (devpi-server 1.2)
--------------------------------------------

devpi-server specific JSON API
++++++++++++++++++++++++++++++++++++++++++

accept and content-type: application/json::
    
    GET  /       -> collection of users 

    GET /user[/] -> user config and indices
    POST /NAME   -> create new user
    PATCH /NAME  -> modify user config
    DEL /NAME    -> del USER (must be logged in or root)

    GET /user/   -> collection of indices

    GET /user/NAME[/] -> get index configuration and per-stage projects
    POST /user/NAME  -> create new index
    DEL  /user/NAME  -> delete new index
    PATCH /user/NAME -> modify index configuration

    GET /user/name/project[/] -> get project info including all versions
    DEL /user/name/project -> delete project along with all versions and files

    GET /user/name/project/version -> get version config
    DEL /user/name/project/version -> delete version config

    GET /user/name/+api -> get api links for the index
    GET /               -> get api links for this server

The idea for this "REST-ish" API design was to view
users, indices, projects and versions as resources in the REST sense.
API calls will also send two headers::

    X-DEVPI-API-VERSION: 2
    X-DEVPI-SERVER-VERSION: {server version}

These headers allow clients to verify if they are going to be able
to work with the content.


setuptools html API
++++++++++++++++++++++++

accept and content-type text/html::

    GET /user/name/PROJECTNAME -> redirect to +simple/PROJECTNAME
    GET /user/name/+simple/PROJECTNAME -> html links to archives
    GET /user/name/+simple/ -> html list of project links

    POST /user/name/  -> html-form upload (release reg, archives, docs, ...)

The setuptools html API (or shortly, "setuptools API") is kind of fixed 
as of May 2014, because it's the API that several version of pip and 
easy_install use.  

Note that ``pip search`` goes to an XMLRPC interface which defaults
to the ``https://pypi.python.org/pypi/`` endpoint and is not changed
from devpi-client because devpi-server does not implement it. 

For your background, details and history of the "html links" content for
a project are described in PEP438.

Other API: documentation
++++++++++++++++++++++++++++++

After documentation zip upload to devpi-server docs are unpacked and
made available as content type ``text/html``::

    GET /user/name/project/version/+doc/*

Other API: index page
+++++++++++++++++++++++++++++

devpi-server-1.2 provides a "summary" page of its projects
and release files and docs.


Search API
--------------------------------------------

ToBeDocumented.
