#! /usr/bin/env python

import os, sys
from setuptools import setup, find_packages

if __name__ == "__main__":
    here = os.path.abspath(".")
    README = open(os.path.join(here, 'README.rst')).read()

    install_requires = ["py>=1.4.18",
                        "devpi_common>=1.2",
                        "execnet>=1.1",
                        "itsdangerous>=0.23",
                        "docutils>=0.11",
                        "pygments>=1.6",
                        "bottle>=0.11.6"]
    if sys.version_info < (2,7):
        install_requires.append("argparse>=1.2.1")

    setup(
      name="devpi-server",
      description="devpi-server: reliable fast pypi.python.org caching server",
      keywords="pypi cache server wsgi",
      long_description=README,
      url="http://doc.devpi.net",
      version='1.2.1',
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
        ] + [
            ("Programming Language :: Python :: %s" % x) for x in
                "2.7 3.3".split()],
      install_requires=install_requires,
      entry_points = {
        'console_scripts':
                    ["devpi-server = devpi_server.main:main"],
      })

