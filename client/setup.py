#! /usr/bin/env python

import sys, os

from setuptools import setup, find_packages

if __name__ == "__main__":
    here = os.path.abspath(".")
    README = open(os.path.join(here, 'README.rst')).read()

    install_requires=["tox>=1.7.1",
                      "devpi_common>2.0.2",
                      "pkginfo>=1.2b1",
                      "check-manifest>=0.21",
                      "py>=1.4.20"]

    if sys.version_info < (2,7):
        install_requires.append("argparse>=1.2.1")

    setup(
      name="devpi-client",
      description="devpi upload/install/... workflow commands for Python "
                  "developers",
      long_description=open("README.rst").read(),
      version='2.0.3.dev',
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
        ] + [
            ("Programming Language :: Python :: %s" % x) for x in
                "2.7 3.3".split()],
      entry_points = {'console_scripts': ["devpi = devpi.main:main"]},
      )
