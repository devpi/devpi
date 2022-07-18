Glossary devpi-server
=====================


.. glossary::

   XOM

      An internal "registry" object which holds several sub components
      as attributes.

      Defined in :mod:`devpi_server.main`. See :class:`devpi_server.main.XOM`


   sro

      :term:`Stage` Resolution Order defines how a name is looked up through
      the bases of a stage.  It's similar to what is known as "MRO" aka method
      resolution order for programming languages.

      See :func:`devpi_server.model.BaseStage._sro`

   stage

      Stage and :term:`index` are used somewhat interchangeably.  ``stage``
      within devpi-server source usually refers to one of:

      - :class:`devpi_server.mirror.MirrorStage`
      - :class:`devpi_server.model.BaseStage`
      - :class:`devpi_server.model.PrivateStage`

   waitress

      The WSGI server that devpi-server runs inside. 
      See http://waitress.readthedocs.org/
