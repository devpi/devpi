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
      version='2.0.1',
      packages=find_packages(),
      install_requires=["requests>=2.3.0", "py>=1.4.20"],
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
      )
