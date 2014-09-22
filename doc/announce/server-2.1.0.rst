devpi-{server-2.1,web-2.2}: upload history, deploy status, groups 
==================================================================

With devpi-server-2.1 and devpi-web-2.2 you'll get a host of fixes
and new features for the private pypi system:

- upload history: release/tests/doc files now carry metadata for 
  by whom, when and to which index something was uploaded

- deployment status: the new json /+status gives detailed information
  about a replica or master's internal state

- a new authentication hook supports arbitrary external authentication 
  systems which can also return "group" membership information.  An initial
  separately released "devpi-ldap" plugin implements verification accordingly.
  You can specify groups in ACLs with the 
  ":GROUPNAME" syntax.  

- a new "--restrict-modify=ACL" option to start devpi-server such that
  only select accounts can create new users or indexes
  
UPGRADE note: devpi-server-2.1 requires to ``--export`` your 2.0
server state and then using ``--import`` with the new version
before you can serve your private packages through devpi-server-2.1.

Please checkout the web plugin if you want to have a web interface::

    http://doc.devpi.net/2.1/web.html

Here is a Quickstart tutorial for efficient pypi-mirroring 
on your laptop::    

    http://doc.devpi.net/2.1/quickstart-pypimirror.html                         
And if you want to manage your releases or implement staging
as an individual or within an organisation::                                    
    http://doc.devpi.net/2.1/quickstart-releaseprocess.html                     
If you want to host a devpi-server installation with nginx/supervisor
and access it from clients from different hosts::
    http://doc.devpi.net/2.1/quickstart-server.html                             
More documentation here::

    http://doc.devpi.net/2.1/                                                

many thanks to Florian Schulze who co-implemented many of the new features.

have fun,

Holger Krekel, merlinux GmbH



