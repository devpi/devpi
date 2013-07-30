
configuring jenkins integration
====================================

.. include:: links.rst

devpi-server can trigger Jenkins to test uploaded packages using tox_.
This needs configuration on two sides:

- devpi: configuring an index to send POST requests to Jenkins upon upload

- Jenkins: adding one or more jobs which can get triggered


Configuring a devpi index to trigger Jenkins
--------------------------------------------------------

Here is a example command, using the default ``/root/dev`` index 
and a Jenkins server at http://localhost:8080::

    # needs one Jenkins job for each name of uploaded packages
    devpi index /root/dev uploadtrigger_jenkins=http://localhost:8080/job/{pkgname}/build

Any package which gets uploaded to ``/root/dev`` will now trigger
a POST request to the specified url.  The ``{pkgname}`` part will be substituted with the name of the uploaded package.  You don't need to specify such
a substitution, however, if you rather want to have one generic Jenkins
job which executes all tests for all your uploads::

    # one generic job for all uploaded packages
    devpi index /root/dev uploadtrigger_jenkins=http://localhost:8080/job/multijob/build

This requires a single ``multijob`` on the Jenkins side whereas the prior
configuration would require a job for each package name that you possibly
upload. 

Note that uploading a package will succeed independently if a build job could
be submitted successfully to Jenkins.

Configuring Jenkins job(s)
--------------------------------------

On the Jenkins side, you need to configure one or more jobs which can
be triggered by devpi-server.  Each job is configured in the same way:

- go to main Jenkins screen

- hit "New Job" and enter a name ("multijob" if you want to configure
  a generic job), then select "freey style software project", hit OK.

.. image:: images/jenkins1.png
   :align: center

- enable "This build is parametrized" and add a "File Parameter",
  setting the file location to ``jobscript.py``.

.. image:: images/jenkins2.png
   :align: center

- add a buildstep "Execute Python script" (you need to have the Python
  plugin installed and enabled in Jenkins) and enter 
  ``execfile("jobscript.py")``.

.. image:: images/jenkins3.png
   :align: center

- hit "Save" for the new build job.

You can now ``devpi upload`` a package to an index and see Jenkins starting
after the upload successfully returns.  


Behind the scenes
-------------------------

Once you triggered a job from devpi, you can checkout the ``jobscript.py``
in the Jenkins workspace to see what was injected.  The injected 
script roughly follows these steps:

- retrieves a stable virtualenv release through the devpi root/pypi
  index (i.e. use its caching ability)

- unpack the virtualenv tar ball and run the contained "virtualenv.py"
  script to create a ``_devpi`` environment

- install/upgrade ``devpi-client`` into that environment

- ``devpi use`` the index which we were triggered from

- ``devpi test PKG`` where PKG is the package name that we uploaded.

