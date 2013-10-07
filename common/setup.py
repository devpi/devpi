#! /usr/bin/env python

import os

from setuptools import setup, find_packages

if __name__ == "__main__":
    here = os.path.abspath(".")
    README = open(os.path.join(here, 'README.rst')).read()
    CHANGES = open(os.path.join(here, 'CHANGELOG')).read()

    setup(
      name="devpi-common",
      description="utilities jointly used by devpi-server and devpi-client",
      long_description=open("README.rst").read(),
      version='0.1.dev1',
      packages=find_packages(),
      url="https://bitbucket.org/hpk42/devpi",
      maintainer="Holger Krekel",
      maintainer_email="holger@merlinux.eu",
      classifiers=[
        "Development Status :: 4 - Beta",
        "Environment :: Web Environment",
        "Intended Audience :: Developers",
        "Intended Audience :: System Administrators",
        "License :: OSI Approved :: MIT License",
        ],
      entry_points = {'console_scripts': ["devpi = devpi.main:main"]},
      )
