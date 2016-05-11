#! /usr/bin/env python

import os
import re

from setuptools import setup, find_packages


def get_changelog():
    text = open(os.path.join(here, 'CHANGELOG')).read()
    header_matches = list(re.finditer('^-+$', text, re.MULTILINE))
    # until fifth header
    text = text[:header_matches[5].start()]
    # all lines without fifth release number
    lines = text.splitlines()[:-1]
    return "Changelog\n=========\n\n" + "\n".join(lines)


if __name__ == "__main__":
    here = os.path.abspath(".")
    README = open(os.path.join(here, 'README.rst')).read()
    CHANGELOG = get_changelog()

    setup(
      name="devpi-common",
      description="utilities jointly used by devpi-server and devpi-client",
      long_description="\n\n".join([README, CHANGELOG]),
      version='2.0.10',
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
