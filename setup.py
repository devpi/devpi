#! /usr/bin/env python

import sys, os

from setuptools import setup

if __name__ == "__main__":
    install_requires=["tox>=1.4.3", "archive>=0.3",
                      "beautifulsoup4", "pip>=1.3.1",
                      "py>=1.4.14", "requests>=1.2.0",]

    if sys.version_info < (2,7):
        install_requires.append("argparse>=1.2.1")

    setup(
      name="devpi",
      description="devpi: packaging workflow commands for Python developers",
      long_description=open("README.rst").read(),
      version='0.7.dev10',
      packages=["devpi", "devpi.util", "devpi.upload",
                "devpi.test", "devpi.test.inject",
      ],
      install_requires=install_requires,
      url="https://bitbucket.org/hpk42/devpi",
      maintainer="Holger Krekel",
      maintainer_email="holger@merlinux.eu",
      classifiers=[
        "Development Status :: 4 - Beta",
        "Environment :: Web Environment",
        "Intended Audience :: Developers",
        "Intended Audience :: System Administrators",
        "License :: OSI Approved :: BSD License",
        ],
      entry_points = {'console_scripts': ["devpi = devpi.main:main"]},
      )
