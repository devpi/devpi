#! /usr/bin/env python

import os, sys
from setuptools import setup, find_packages

if __name__ == "__main__":
    here = os.path.abspath(".")
    README = open(os.path.join(here, 'README.rst')).read()
    CHANGES = open(os.path.join(here, 'CHANGES.txt')).read()

    install_requires = ["py", "beautifulsoup4>=4.1.3", "requests",
                        "redis>=2.7.2", "bottle"]

    setup(
      name="devpi-server",
      description="devpi-server: reliable fast pypi.python.org caching server",
      keywords="pypi cache server wsgi",
      long_description=README + '\n\n' + CHANGES,
      version='0.7',
      maintainer="Holger Krekel",
      maintainer_email="holger@merlinux.eu",
      packages=find_packages(),
      include_package_data=True,
      zip_safe=False,
      license="MIT",
      classifiers=[
        "Development Status :: 4 - Beta",
        "Environment :: Web Environment",
        "Intended Audience :: Developers",
        "Intended Audience :: System Administrators",
        "License :: OSI Approved :: MIT License",
        "Programming Language :: Python",
        "Framework :: Pyramid",
        "Topic :: Internet :: WWW/HTTP",
        "Topic :: Internet :: WWW/HTTP :: WSGI :: Application",
        ],
      install_requires=install_requires,
      entry_points = {
        'console_scripts':
                    ["devpi-server = devpi_server.main:main"],
      })

