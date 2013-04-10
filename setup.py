#! /usr/bin/env python

from setuptools import setup

if __name__ == "__main__":
    setup(
      name="devpi-server",
      description="devpi caching indexes server",
      version='0.6.dev10',
      packages=["devpi_server", "testing"],
      maintainer="Holger Krekel",
      maintainer_email="holger@merlinux.eu",
      license="MIT",
      classifiers=[
        "Development Status :: 4 - Beta",
        "Environment :: Web Environment",
        "Intended Audience :: Developers",
        "Intended Audience :: System Administrators",
        "License :: OSI Approved :: BSD License",
        ],
      install_requires=["beautifulsoup4", "argparse"],
      entry_points = {'console_scripts':
            ["devpi-server = devpi_server.main:main"]},
      )
