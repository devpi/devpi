#! /usr/bin/env python

import os
import re

from codecs import open

from setuptools import find_packages, setup

here = os.path.abspath(os.path.dirname(__file__))


def get_changelog():
    with open(os.path.join(here, 'CHANGELOG'), encoding='utf-8') as f:
        text = f.read()
    header_matches = list(re.finditer('^=+$', text, re.MULTILINE))
    text = text[:header_matches[5].start()] # until fifth header
    lines = text.splitlines()[:-1] # all lines without fifth release number
    return '=========\nChangelog\n=========\n\n' + '\n'.join(lines)

about = {}

with open(os.path.join(here, 'devpi_server', '__version__.py'), 'r', 'utf-8') as f:
    exec(f.read(), about)

with open('README.rst', encoding='utf-8') as f:
    README = f.read()

CHANGELOG = get_changelog()

requires = [
        'py>=1.4.23',
        'appdirs',
        'devpi_common<4,>=3.3.0',
        'itsdangerous>=0.24',
        'execnet>=1.2',
        'pyramid>=1.8',
        'waitress>=1.0.1',
        'repoze.lru>=0.6',
        'passlib[argon2]',
        'pluggy>=0.3.0,<1.0',
        'strictyaml',
        ]
extras_require = {}

setup(
    name=about['__title__'],
    description=about['__description__'],
    keywords='pypi realtime cache server',
    long_description="\n\n".join([README, CHANGELOG]),
    url=about['__url__'],
    version=about['__version__'],
    maintainer=about['__maintainer__'],
    maintainer_email=about['__maintainer_email__'],
    packages=find_packages(),
    include_package_data=True,
    zip_safe=False,
    license=about['__license__'],
    classifiers=[
        'Development Status :: 5 - Production/Stable',
        'Environment :: Web Environment',
        'Intended Audience :: Developers',
        'Intended Audience :: System Administrators',
        'License :: OSI Approved :: MIT License',
        'Programming Language :: Python',
        'Topic :: Internet :: WWW/HTTP',
        'Topic :: Internet :: WWW/HTTP :: WSGI :: Application',
        'Programming Language :: Python :: Implementation :: PyPy',
        'Programming Language :: Python :: 2.7',
        'Programming Language :: Python :: 3.4',
        'Programming Language :: Python :: 3.5',
        'Programming Language :: Python :: 3.6',
        ],
    install_requires=requires,
    extras_require=extras_require,
    entry_points={
        'console_scripts': [
            'devpi-server = devpi_server.main:main' ],
        'devpi_server': [
            'devpi-server-auth-basic = devpi_server.auth_basic',
            'devpi-server-auth-devpi = devpi_server.auth_devpi',
            'devpi-server-sqlite = devpi_server.keyfs_sqlite',
            'devpi-server-sqlite-fs = devpi_server.keyfs_sqlite_fs' ],
        'devpi_web': [
            'devpi-server-status = devpi_server.views'],
        'pytest11': [
            'pytest_devpi_server = pytest_devpi_server' ],
        },
    )
