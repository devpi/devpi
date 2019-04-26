from setuptools import setup
import io
import os
import re


def get_changelog():
    here = os.path.abspath(".")
    text = io.open(os.path.join(here, 'CHANGELOG'), encoding='utf-8').read()
    header_matches = list(re.finditer('^=+$', text, re.MULTILINE))
    # until fifth header
    text = text[:header_matches[5].start()]
    # all lines without fifth release number
    lines = text.splitlines()[:-1]
    return "=========\nChangelog\n=========\n\n" + "\n".join(lines)


README = io.open(os.path.abspath('README.rst'), encoding='utf-8').read()
CHANGELOG = get_changelog()


setup(
    name="devpi-web",
    description="devpi-web: a web view for devpi-server",
    long_description="\n\n".join([README, CHANGELOG]),
    url="http://doc.devpi.net",
    version='3.5.1',
    maintainer="Holger Krekel, Florian Schulze",
    maintainer_email="holger@merlinux.eu",
    license="MIT",
    classifiers=[
        "Development Status :: 5 - Production/Stable",
        "Environment :: Web Environment",
        "Intended Audience :: Developers",
        "Intended Audience :: System Administrators",
        "License :: OSI Approved :: MIT License",
        "Programming Language :: Python",
        "Topic :: Internet :: WWW/HTTP",
        "Programming Language :: Python :: Implementation :: PyPy",
        "Topic :: Internet :: WWW/HTTP :: WSGI :: Application"] + [
            "Programming Language :: Python :: %s" % x
            for x in "2.7 3.4 3.5 3.6".split()],
    entry_points={
        'devpi_server': [
            "devpi-web = devpi_web.main"],
        'devpi_web': [
            "devpi-web-null = devpi_web.null_index",
            "devpi-web-whoosh = devpi_web.whoosh_index"]},
    install_requires=[
        'Whoosh<3',
        'beautifulsoup4>=4.3.2',
        'defusedxml',
        'devpi-server>=4.2.1',
        'devpi-common>=3.2.0',
        'docutils>=0.11',
        'pygments>=1.6',
        'pyramid!=1.10a1',
        'pyramid-chameleon',
        'readme-renderer[md]>=23.0'],
    include_package_data=True,
    zip_safe=False,
    packages=['devpi_web'])
