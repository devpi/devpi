from setuptools import setup
import os
import re


def get_changelog():
    here = os.path.abspath(".")
    text = open(os.path.join(here, 'CHANGELOG')).read()
    header_matches = list(re.finditer('^-+$', text, re.MULTILINE))
    # until fifth header
    text = text[:header_matches[:5][-1].start()]
    # all lines without fifth release number
    lines = text.splitlines()[:-1]
    return "Changelog\n=========\n\n" + "\n".join(lines)


README = open(os.path.abspath('README.rst')).read()
CHANGELOG = get_changelog()


setup(
    name="devpi-postgresql",
    description="devpi-postgresql: a PostgreSQL storage backend for devpi-server",
    long_description="\n\n".join([README, CHANGELOG]),
    url="http://doc.devpi.net",
    version='0.1.0',
    maintainer="Florian Schulze, Holger Krekel",
    maintainer_email="florian.schulze@gmx.net",
    license="MIT",
    classifiers=[
        "Development Status :: 4 - Beta",
        "Environment :: Web Environment",
        "Intended Audience :: Developers",
        "Intended Audience :: System Administrators",
        "License :: OSI Approved :: MIT License",
        "Programming Language :: Python",
        "Topic :: Internet :: WWW/HTTP",
        "Programming Language :: Python :: Implementation :: PyPy",
        "Topic :: Internet :: WWW/HTTP :: WSGI :: Application"] + [
            "Programming Language :: Python :: %s" % x
            for x in "2.7 3.3".split()],
    entry_points={
        'devpi_server': [
            "devpi-postgresql = devpi_postgresql.main"]},
    install_requires=[
        'devpi-server>=3.0.0.dev2',
        'pg8000'],
    include_package_data=True,
    zip_safe=False,
    packages=['devpi_postgresql'])
