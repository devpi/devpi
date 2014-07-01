#! /usr/bin/env python

import os
from setuptools import setup

if __name__ == "__main__":
    here = os.path.abspath(".")
    README = open(os.path.join(here, 'README.rst')).read()

    setup(
      name="devpi",
      description="devpi: github-style pypi index server and packaging meta tool.",
      install_requires = ["devpi-server>=2.0.0.dev1,<2.1",
                          "devpi-client>=2.0.0.dev1,<2.1"],
      keywords="pypi cache server installer wsgi",
      long_description=README,
      url="http://doc.devpi.net",
      version='2.0.0.dev1',
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
