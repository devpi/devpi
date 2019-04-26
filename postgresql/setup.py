from setuptools import setup
import io
import os
import re


def get_changelog():
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
    url="http://doc.devpi.net",
    version='1.0.0',
    maintainer="Florian Schulze, Holger Krekel",
    maintainer_email="florian.schulze@gmx.net",
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
            for x in "3.4 3.5 3.6".split()],
    entry_points={
        'devpi_server': [
            "devpi-postgresql = devpi_postgresql.main"],
        'pytest11': [
            "pytest_devpi_postgresql = pytest_devpi_postgresql"]},
    install_requires=[
        'devpi-server>=3.0.0.dev2',
        'pg8000'],
    include_package_data=True,
    python_requires='>=3.4',
    zip_safe=False,
    packages=['devpi_postgresql', 'pytest_devpi_postgresql'])
