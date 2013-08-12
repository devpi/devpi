devpi server: controling the automatic server
+++++++++++++++++++++++++++++++++++++++++++++

Let's look at our current automatically started server::

    $ devpi server 
    server is running with pid 8041

Let's stop it::

    $ devpi server --stop
    killed server pid=8041

Note that with most ``devpi`` commands the server will be started
up again when needed.  As soon as you start ``devpi use`` with 
any other root url than ``http://localhost:3141`` no automatic 
server management takes place anymore.

uploading sphinx docs
++++++++++++++++++++++++++++++++

If you have sphinx-based docs you can upload them as well::

    devpi upload --with-docs

This will build and upload sphinx-documentation by configuring and running
this command::

    setup.py build_sphinx -E --build-dir $BUILD_DIR \
             upload_docs --upload-dir $BUILD_DIR/html


bulk uploading release files
++++++++++++++++++++++++++++++++

If you have a directory with existing package files::

    devpi upload --from-dir PATH/TO/DIR

will recursively collect all archives files, register
and upload them to our local ``root/dev`` pypi index.
