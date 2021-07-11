#! /usr/bin/env python

import os
import re
import io
import sys
from setuptools import setup


def get_changelog():
    if 'bdist_rpm' in sys.argv:
        # exclude changelog when building rpm
        return ""
    with io.open(os.path.join(here, 'CHANGELOG'), encoding="utf-8") as f:
        text = f.read()
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

    install_requires = ["py>=1.4.23",
                        "appdirs",
                        "argon2-cffi",
                        "attrs",
                        "defusedxml",
                        "devpi_common<4,>=3.3.0",
                        "itsdangerous>=0.24",
                        "execnet>=1.2",
                        "pyramid>=2",
                        "waitress>=1.0.1",
                        "repoze.lru>=0.6",
                        "passlib[argon2]",
                        "pluggy>=0.6.0,<1.0",
                        'ruamel.yaml',
                        "strictyaml",
                        ]
    extras_require = {}

    setup(
      name="devpi-server",
      description="devpi-server: reliable private and pypi.org caching server",
      keywords="pypi realtime cache server",
      long_description="\n\n".join([README, CHANGELOG]),
      url="https://devpi.net",
      project_urls={
        'Bug Tracker': 'https://github.com/devpi/devpi/issues',
        'Changelog': 'https://github.com/devpi/devpi/blob/main/server/CHANGELOG',
        'Documentation': 'https://doc.devpi.net',
        'Source Code': 'https://github.com/devpi/devpi'
      },
      version='6.1.0',
      maintainer="Holger Krekel, Florian Schulze",
      maintainer_email="holger@merlinux.eu",
      packages=[
        'devpi_server',
        'devpi_server.cfg',
        'pytest_devpi_server',
        'test_devpi_server'],
      include_package_data=True,
      zip_safe=False,
      license="MIT",
      classifiers=[
        "Development Status :: 5 - Production/Stable",
        "Environment :: Web Environment",
        "Intended Audience :: Developers",
        "Intended Audience :: System Administrators",
        "License :: OSI Approved :: MIT License",
        "Programming Language :: Python",
        "Programming Language :: Python :: 3 :: Only",
        "Topic :: Internet :: WWW/HTTP",
        "Topic :: Internet :: WWW/HTTP :: WSGI :: Application",
        "Programming Language :: Python :: Implementation :: PyPy",
      ] + [
            ("Programming Language :: Python :: %s" % x)
            for x in "3.6 3.7 3.8".split()],
      install_requires=install_requires,
      extras_require=extras_require,
      python_requires='>=3.6',
      entry_points={
        'console_scripts': [
            "devpi-export = devpi_server.importexport:export",
            "devpi-fsck = devpi_server.fsck:fsck",
            "devpi-gen-config = devpi_server.genconfig:genconfig",
            "devpi-gen-secret = devpi_server.config:gensecret",
            "devpi-import = devpi_server.importexport:import_",
            "devpi-init = devpi_server.init:init",
            "devpi-passwd = devpi_server.passwd:passwd",
            "devpi-server = devpi_server.main:main"],
        'devpi_server': [
            "devpi-server-auth-basic = devpi_server.auth_basic",
            "devpi-server-auth-devpi = devpi_server.auth_devpi",
            "devpi-server-extpypi = devpi_server.extpypi",
            "devpi-server-genconfig = devpi_server.genconfig",
            "devpi-server-model = devpi_server.model",
            "devpi-server-replica = devpi_server.replica",
            "devpi-server-view-auth = devpi_server.view_auth",
            "devpi-server-views = devpi_server.views",
            "devpi-server-sqlite = devpi_server.keyfs_sqlite",
            "devpi-server-sqlite-fs = devpi_server.keyfs_sqlite_fs"],
        'devpi_web': [
            "devpi-server-replica-status = devpi_server.replica",
            "devpi-server-status = devpi_server.views"],
        'pytest11': [
            "pytest_devpi_server = pytest_devpi_server"]})
