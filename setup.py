#! /usr/bin/env python

import os, sys
from setuptools import setup, find_packages

if __name__ == "__main__":
    here = os.path.abspath(".")
    README = open(os.path.join(here, 'README.rst')).read()
    CHANGES = open(os.path.join(here, 'CHANGELOG')).read()

    install_requires = ["py>=1.4.13",
                        "requests>=1.2.0",
                        "redis>=2.7.2",
                        "bottle>=0.11.6"]
    if sys.version_info < (2,7):
        install_requires.append("argparse")

    setup(
      name="devpi-server",
      description="devpi-server: reliable fast pypi.python.org caching server",
      keywords="pypi cache server wsgi",
      long_description=README + '\n\n' + CHANGES,
      version='0.8.5',
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
        "Topic :: Internet :: WWW/HTTP",
        "Topic :: Internet :: WWW/HTTP :: WSGI :: Application",
        ],
      install_requires=install_requires,
      entry_points = {
        'console_scripts':
                    ["devpi-server = devpi_server.main:main"],
      })

