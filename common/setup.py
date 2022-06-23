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

    setup(
      name="devpi-common",
      description="utilities jointly used by devpi-server and devpi-client",
      long_description="\n\n".join([README, CHANGELOG]),
      version='3.6.1.dev0',
      packages=['devpi_common', 'devpi_common.vendor'],
      install_requires=[
          "lazy",
          "py>=1.4.20",
          "requests>=2.3.0"],
      python_requires=">=2.7, !=3.0.*, !=3.1.*, !=3.2.*, !=3.3.*",
      url="https://github.com/devpi/devpi",
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
          ("Programming Language :: Python :: %s" % x)
          for x in "2.7 3.4 3.5 3.6 3.7".split()],
      )
