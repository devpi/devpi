==========================
Developers' guide to devpi
==========================


Glossary
========


.. glossary::

   BackgroundServer

      ???

      Defined in :mod:`devpi_server.bgserver`. See :class:`devpi_server.bgserver.BackgroundServer`.

      .. todo::

         What is the purpose of this?

   sro

      :term:`Stage` Resolution Order

      See :func:`devpi_server.model.BaseStage._sro`

   stage

      Same as an :term:`index`?

      One of:

      - :class:`devpi_server.model.BaseStage`
      - :class:`devpi_server.model.PrivateStage`
      - :class:`devpi_server.extpypi.PyPIStage`

   waitress

      The WSGI server that devpi-server runs inside. See http://waitress.readthedocs.org/

   XOM

      ???

      Defined in :mod:`devpi_server.main`. See :class:`devpi_server.main.XOM`

   XProcess

      ???

      Defined in :mod:`devpi_server.vendor.xprocess`. See :class:`devpi_server.vendor.xprocess.XProcess`

      .. todo::

         What is the purpose of this?
