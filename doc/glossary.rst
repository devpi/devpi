
Glossary
========


.. glossary::

   index
   
      A (package) index is a repository for release metadata and release files.
      devpi-server allows the creation of multiple independent indices per user.

   non volatile index 
   
      An index which can not be deleted or modified in a destructive manner. 
      Typically, **non volatile indexes** are indexes shared amongts users
      part of a project or an organization. For more details see 
      :ref:`non_volatile_indexes`.
      
   volatile index
   
      A index that can be modified and deleted at will be its owner.  
      On upload, release files will overwrite existing release files.
      A Development index is an example of volatile indexes. A volatile 
      index normally pertains to a single user. 
      
   acl
   
      Access Control List

   upload
   
      Action consisting of loading one or more release files from a file 
      system to an index. 
   
   push
   
      Action of transfering a package from one index to another. 

   remove

      Action of deleting a project or a specific release from an index.
      
   release file
   
      A release file contains a project's artifact (.py files, etc) required
      for the installation. A release file is versioned. The term *package* 
      is often use as well, but might be confused with a *python package*.

   volatile
      
      Indices have a boolean "volatile" property.  If true, release files can
      be deleted or replaced.  If False, attempts at modifications will 
      cause an Error.
    
   
