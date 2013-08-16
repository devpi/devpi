
.. _overview:

Overview
========

This package consists of a single module with a single function
returning the package version.

The associated test verifies that the version passed on the command
line matches the package version::

   $ py.test -v
   ===================== test session starts ========================
   platform linux2 -- Python 2.7.3 -- pytest-2.3.5 -- ...
   collected 1 items 
   
   test/test_pysober.py:4: test_version PASSED
   
   ===================== 1 passed in 0.02 seconds ===================

or::

   $ py.test -v --project-version='1.1.0'
   ===================== test session starts ========================
   platform linux2 -- Python 2.7.3 -- pytest-2.3.5 -- ...
   collected 1 items 
   
   test/test_pysober.py:4: test_version FAILED
   
   ===================== FAILURES ===================================
   _____________________ test_version _______________________________
   
   pysober_expected_version = '1.1.0'
   
       def test_version(pysober_expected_version):
   >       assert pysober_expected_version == __version__
   E       assert '1.1.0' == '0.1.0'
   E         - 1.1.0
   E         ? ^
   E         + 0.1.0
   E         ? ^
   
   test/test_pysober.py:5: AssertionError
   =====================  1 failed in 0.02 seconds ================== 

Background
----------

For the purpose of documenting devpi's user manual.

Goals
-----

I am still trying to figure this one out :) 
