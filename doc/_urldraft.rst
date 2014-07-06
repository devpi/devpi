
current URL API scheme (devpi-server 1.2)
--------------------------------------------

devpi-server specific JSON API
++++++++++++++++++++++++++++++++++++++++++

accept and content-type: application/json::
    
    GET  /       -> collection of users 

    GET /user    -> user config
    POST /NAME   -> create new user
    PATCH /NAME  -> modify user config
    DEL /NAME    -> del USER (must be logged in or root)

    GET /user/   -> collection of indices

    GET /user/NAME   -> modify index configuration
    POST /user/NAME  -> create new index
    DEL  /user/NAME  -> delete new index
    PATCH /user/NAME -> modify index configuration

    GET /user/name/project -> get project config
    DEL /user/name/project -> delete project config

    GET /user/name/project/version -> get version config
    DEL /user/name/project/version -> delete version config

    GET /user/name/**/+api
                    -> get api links for the index

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


Next version API
--------------------------------------------

For mirroring and search we will need to enrich the API.
There is also the question if we want to redo or enhance the
existing API scheme.  But let's first try to incrementally 
add mirroring and search API:

    GET /+search [json]
        # json body describes a search query and will return json
        # with the matches
        
    GET/POST /+search [html]
        # shows/accepts search form
        
    GET/POST /user/name/+search [html]
        # shows/accepts index-specific search form

    GET /+mirror [x-devpi-mirror]        
        # json body describes a mirroring request
        # (init/subscribe) for mirroring
        # returns long-polling updates
