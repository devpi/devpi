devpi-server-4.0: fixing the pip-8.1.2 problem
============================================================================

We've made critically important releases of the devpi private packaging
system available (see http://doc.devpi.net for documentation).

For the many who experienced the "pip doesn't install packages anymore with devpi"
problem you can, first of all, pin "pip" to avoid the problem on the client side:
 
    pip install pip==8.1.1

This is obviously a crotch but gives you some time to perform the
export/import cycle required for hosting private packages via
devpi-server-4.0 and using pip-8.1.2.

If you using devpi-server as a pure pypi.python.org cache you don't 
actually need to perform export/import and can just wipe your server directory 
($HOME/.devpi/server by default) before you install and start up 
devpi-server-4.0.

If you are hosting private packages on devpi you will need to perform an
export/import cycle of your server state in order to run devpi-server-4.0.
The "4.0" in this case only signals this export/import need -- no other
big changes are coming with 4.0.  At the end of this announcement we explain 
some details of why we needed to go for a 4.0 and not just a micro bugfix release.


To export from devpi-server-3.X
--------------------------------

upgrade to the new devpi-server-3.1.2 before you export, like this:

    pip install "devpi-server<4.0" 

Now stop your server and run:

    devpi-server --export EXPORTDIR --serverdir SERVERDIR

where EXPORTDIR should be a fresh new directory and SERVERDIR
should be the server state directory ($HOME/.devpi/server by default).

To export from devpi-server-2.X
--------------------------------

Upgrade to the latest devpi-server-2.X release:

    pip install "devpi-server<3.0" devpi-common>=2.0.10

Here we force the devpi-common dependency to not accidentally
be "devpi-common==2.0.9" which could lead to problems.

Now stop your server and run:

    devpi-server --export EXPORTDIR --serverdir SERVERDIR

where EXPORTDIR should be a fresh new directory and SERVERDIR
should be the server state directory ($HOME/.devpi/server by default).


to import state into devpi-server-4.0
----------------------------------------

Upgrade to the latest devpi-server.4.X release:

    pip install "devpi-server<5.0" devpi-web

If you don't use "devpi-web" you can leave it out from the pip command.
Check you have the right version:

    devpi-server --version

Now import from your previously created EXPORTDIR:

    devpi-server --serverdir SERVERDIR_NEW --import EXPORTDIR

This will take a while if you have many indexes or lots of documentation --
devpi-web will create a search index over all of it during import.

You are now good to go -- pip works again!


background on the pip/devpi bug for the curious
-----------------------------------------------

Besides devpi, also artifactory and other private index servers
have experienced failures with pip-8.1.2.  The change from 8.1.1
was that pip now asks for PEP503-normalized names when requesting
the simple page from an index.  Previously "-" and "." would be
allowed but with the new normalization "." is substituted with "-".
Now "pip install zope.interface" triggers a request to 
"+simple/zope-interface" and devpi in turns asks 
pypi.python.org/simple/zope-interface and gets an answer
with lots of "zope.interface-*.tar.gz" release links. But those
are not matched because without PEP503 "zope.interface" and "zope-interface"
are different things.  Moreover, pypi.python.org used to redirect 
to the "true" name but does not do this anymore which contributed
to the eventual problem.

We decided to go for 4.0 because since 3.0 we base database
keys on normalized project names -- and this normalization is
used in like 20-30 code places across the devpi system and plugins.
Trying to be clever and avoid the export/import and trick "pip-8.1.2"
into working looked like a can of worms.  Now with devpi-server-4.0
we are using proper PEP503 specified normalization so should be safe.

best,
holger and florian

P.S.: we offer support contracts btw and thank in particular
Dolby Laboratories, YouGov Inc and BlueYonder GmbH who funded a lot of
the last year's devpi work and now agreed to be named in public - and
no, we didn't get around to make a flashy web site yet.  For now,
just mail holger at merlinux to discuss support and training options.
