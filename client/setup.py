#! /usr/bin/env python

import io
import os
import re
import sys

from setuptools import setup


def get_changelog():
    if 'bdist_rpm' in sys.argv:
        # exclude changelog when building rpm
        return ""
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

    install_requires = [
        "build",
        "check-manifest>=0.28",
        "devpi_common<4,>=3.6.0",
        "iniconfig",
        "pep517",
        "pkginfo>=1.4.2",
        "platformdirs",
        "pluggy>=0.6.0,<2.0",
        "py>=1.4.31"]

    extras_require = {}

    setup(
      name="devpi-client",
      description="devpi upload/install/... workflow commands for Python "
                  "developers",
      long_description="\n\n".join([README, CHANGELOG]),
      version='6.0.2',
      packages=['devpi'],
      install_requires=install_requires,
      extras_require=extras_require,
      python_requires=">=2.7, !=3.0.*, !=3.1.*, !=3.2.*, !=3.3.*",
      url="https://devpi.net",
      project_urls={
          'Bug Tracker': 'https://github.com/devpi/devpi/issues',
          'Changelog': 'https://github.com/devpi/devpi/blob/main/client/CHANGELOG',
          'Documentation': 'https://doc.devpi.net',
          'Source Code': 'https://github.com/devpi/devpi'
      },
      maintainer="Florian Schulze",
      maintainer_email="mail@pyfidelity.com",
      license="MIT",
      classifiers=[
        "Development Status :: 5 - Production/Stable",
        "Environment :: Web Environment",
        "Intended Audience :: Developers",
        "Intended Audience :: System Administrators",
        "License :: OSI Approved :: MIT License",
        "Programming Language :: Python :: Implementation :: PyPy",
        ] + [
            ("Programming Language :: Python :: %s" % x) for x in
            "2.7 3.4 3.5 3.6 3.7 3.8 3.9 3.10".split()],
      entry_points = {
        'console_scripts': [
          "devpi = devpi.main:main"],
        'devpi_client': [
          "devpi-client-login = devpi.login",
          "devpi-client-subcommands = devpi.main"]}
      )
