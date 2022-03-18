from setuptools import setup
import io
import os
import re
import sys


def get_changelog():
    if 'bdist_rpm' in sys.argv:
        # exclude changelog when building rpm
        return ""
    here = os.path.abspath(".")
    with io.open(os.path.join(here, 'CHANGELOG'), encoding="utf-8") as f:
        text = f.read()
    header_matches = list(re.finditer('^=+$', text, re.MULTILINE))
    # until fifth header
    if len(header_matches) > 5:
        text = text[:header_matches[5].start()]
        # all lines without fifth release number
        lines = text.splitlines()[:-1]
    else:
        lines = text.splitlines()
    return "=========\nChangelog\n=========\n\n" + "\n".join(lines)


README = io.open(os.path.abspath('README.rst'), encoding='utf-8').read()
CHANGELOG = get_changelog()


setup(
    name="devpi-postgresql",
    description="devpi-postgresql: a PostgreSQL storage backend for devpi-server",
    long_description="\n\n".join([README, CHANGELOG]),
    url="https://devpi.net",
    project_urls={
        'Bug Tracker': 'https://github.com/devpi/devpi/issues',
        'Changelog': 'https://github.com/devpi/devpi/blob/main/postgresql/CHANGELOG',
        'Documentation': 'https://doc.devpi.net',
        'Source Code': 'https://github.com/devpi/devpi'
    },
    version='3.0.0',
    maintainer="Florian Schulze",
    maintainer_email="mail@pyfidelity.com",
    license="MIT",
    classifiers=[
        "Development Status :: 4 - Beta",
        "Environment :: Web Environment",
        "Intended Audience :: Developers",
        "Intended Audience :: System Administrators",
        "License :: OSI Approved :: MIT License",
        "Programming Language :: Python :: 3 :: Only",
        "Topic :: Internet :: WWW/HTTP",
        "Programming Language :: Python :: Implementation :: PyPy",
        "Topic :: Internet :: WWW/HTTP :: WSGI :: Application"] + [
            "Programming Language :: Python :: %s" % x
            for x in "3.7 3.8 3.9 3.10".split()],
    entry_points={
        'devpi_server': [
            "devpi-postgresql = devpi_postgresql.main"],
        'pytest11': [
            "pytest_devpi_postgresql = pytest_devpi_postgresql"]},
    install_requires=[
        'devpi-server>=6.2.0',
        'pg8000>=1.17.0'],
    include_package_data=True,
    python_requires='>=3.7',
    zip_safe=False,
    packages=['devpi_postgresql', 'pytest_devpi_postgresql'])
