#! /usr/bin/env python

import io
import os, re

from setuptools import setup, find_packages


def get_changelog():
    text = io.open(os.path.join(here, 'CHANGELOG'), encoding='utf-8').read()
    header_matches = list(re.finditer('^=+$', text, re.MULTILINE))
    # until fifth header
    text = text[:header_matches[5].start()]
    # all lines without fifth release number
    lines = text.splitlines()[:-1]
    return "=========\nChangelog\n=========\n\n" + "\n".join(lines)


if __name__ == "__main__":
    here = os.path.abspath(".")
    README = io.open(os.path.join(here, 'README.rst'), encoding='utf-8').read()
    CHANGELOG = get_changelog()

    install_requires=["tox>=3.1.0",
                      "devpi_common<4,>=3.1.0",
                      "pkginfo>=1.4.2",
                      "check-manifest>=0.28",
                      "pluggy>=0.6.0,<1.0",
                      "py>=1.4.31"]

    extras_require = {}

    setup(
      name="devpi-client",
      description="devpi upload/install/... workflow commands for Python "
                  "developers",
      long_description="\n\n".join([README, CHANGELOG]),
      version='4.4.0',
      packages=find_packages(),
      install_requires=install_requires,
      extras_require=extras_require,
      url="https://github.com/devpi/devpi",
      maintainer="Holger Krekel",
      maintainer_email="holger@merlinux.eu",
      classifiers=[
        "Development Status :: 5 - Production/Stable",
        "Environment :: Web Environment",
        "Intended Audience :: Developers",
        "Intended Audience :: System Administrators",
        "License :: OSI Approved :: MIT License",
        "Programming Language :: Python :: Implementation :: PyPy",
        ] + [
            ("Programming Language :: Python :: %s" % x) for x in
                "2.7 3.4 3.5 3.6".split()],
      entry_points = {
        'console_scripts': [
          "devpi = devpi.main:main"],
        'devpi_client': [
          "devpi-client-login = devpi.login",
          "devpi-client-subcommands = devpi.main"]}
      )
