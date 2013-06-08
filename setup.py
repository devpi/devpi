#! /usr/bin/env python

import os, sys
from setuptools import setup

if __name__ == "__main__":
    here = os.path.abspath(".")
    README = open(os.path.join(here, 'README.rst')).read()
    CHANGES = open(os.path.join(here, 'CHANGELOG')).read()

    setup(
      name="devpi",
      description="devpi: github-style pypi index server and packaging meta tool.",
      install_requires = ["devpi-server>=0.9", "devpi-client>=0.9"],
      keywords="pypi cache server installer wsgi",
      long_description=README + '\n\n' + CHANGES,
      url="http://doc.devpi.net",
      version='0.9.dev8',
      maintainer="Holger Krekel",
      maintainer_email="holger@merlinux.eu",
      zip_safe=False,
      license="MIT",
      classifiers=[
        "Development Status :: 4 - Beta",
        "Environment :: Web Environment",
        "Intended Audience :: Developers",
        "Intended Audience :: System Administrators",
        "License :: OSI Approved :: MIT License",
        "Programming Language :: Python",
        "Topic :: Internet :: WWW/HTTP",
        "Topic :: Internet :: WWW/HTTP :: WSGI :: Application",
        ],
      )

