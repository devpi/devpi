#! /usr/bin/env python

import sys, os

from setuptools import setup, find_packages

if __name__ == "__main__":
    here = os.path.abspath(".")
    README = open(os.path.join(here, 'README.rst')).read()
    CHANGES = open(os.path.join(here, 'CHANGELOG')).read()

    install_requires=["tox>=1.4.3", "archive>=0.3", "beautifulsoup4>=4.2.1",
                      #"pip>=1.3.1",
                      "pkginfo>=1.1b1",
                      "py>=1.4.14", "requests>=1.2.2",]

    if sys.version_info < (2,7):
        install_requires.append("argparse>=1.2.1")

    setup(
      name="devpi-client",
      description="devpi upload/install/... workflow commands for Python "
                  "developers",
      long_description=open("README.rst").read(),
      version='0.9.5.dev3',
      packages=find_packages(),
      install_requires=install_requires,
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
