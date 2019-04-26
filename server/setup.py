#! /usr/bin/env python

import os, re
import io
from setuptools import setup, find_packages


def get_changelog():
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
                        "devpi_common<4,>=3.3.0",
                        "itsdangerous>=0.24",
                        "execnet>=1.2",
                        "pyramid>=1.8",
                        "waitress>=1.0.1",
                        "repoze.lru>=0.6",
                        "passlib[argon2]",
                        "pluggy>=0.6.0,<1.0",
                        "strictyaml",
                        ]
    extras_require = {}

    setup(
      name="devpi-server",
      description="devpi-server: reliable private and pypi.org caching server",
      keywords="pypi realtime cache server",
      long_description="\n\n".join([README, CHANGELOG]),
      url="http://doc.devpi.net",
      version='4.9.0',
      maintainer="Holger Krekel, Florian Schulze",
      maintainer_email="holger@merlinux.eu",
      packages=find_packages(),
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
        "Topic :: Internet :: WWW/HTTP",
        "Topic :: Internet :: WWW/HTTP :: WSGI :: Application",
        "Programming Language :: Python :: Implementation :: PyPy",
        ] + [
            ("Programming Language :: Python :: %s" % x) for x in
                "2.7 3.4 3.5 3.6".split()],
      install_requires=install_requires,
      extras_require=extras_require,
      entry_points = {
        'console_scripts':
                    ["devpi-server = devpi_server.main:main"],
        'devpi_server': [
            "devpi-server-auth-basic = devpi_server.auth_basic",
            "devpi-server-auth-devpi = devpi_server.auth_devpi",
            "devpi-server-sqlite = devpi_server.keyfs_sqlite",
            "devpi-server-sqlite-fs = devpi_server.keyfs_sqlite_fs"],
        'devpi_web': [
            "devpi-server-status = devpi_server.views"],
        'pytest11': [
            "pytest_devpi_server = pytest_devpi_server"]})
