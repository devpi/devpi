#! /usr/bin/env python

import os, sys
import setuptools
from setuptools import setup, find_packages

def has_environment_marker_support():
    """
    Tests that setuptools has support for PEP-426 environment marker support.

    The first known release to support it is 0.7 (and the earliest on PyPI seems to be 0.7.2
    so we're using that), see: http://pythonhosted.org/setuptools/history.html#id142

    References:

    * https://wheel.readthedocs.org/en/latest/index.html#defining-conditional-dependencies
    * https://www.python.org/dev/peps/pep-0426/#environment-markers
    """
    import pkg_resources
    try:
        return pkg_resources.parse_version(setuptools.__version__) >= pkg_resources.parse_version('0.7.2')
    except Exception as exc:
        sys.stderr.write("Could not test setuptool's version: %s\n" % exc)
        return False

if __name__ == "__main__":
    here = os.path.abspath(".")
    README = open(os.path.join(here, 'README.rst')).read()

    install_requires = ["py>=1.4.23",
                        "devpi_common<2.1,>=2.0.6.dev0",
                        "itsdangerous>=0.24",
                        "execnet>=1.2",
                        "pyramid>=1.5.1",
                        "waitress>=0.8.9",
                        "repoze.lru>=0.6",
                        "pluggy>=0.2.0,<1.0",
                        "pyyaml>=3.0",
                        ]
    extras_require = {}
    if has_environment_marker_support():
        extras_require[':python_version=="2.6"'] = ['argparse']
    elif sys.version_info < (2,7):
        install_requires.append("argparse>=1.2.1")

    setup(
      name="devpi-server",
      description="devpi-server: reliable private and pypi.python.org caching server",
      keywords="pypi realtime cache server",
      long_description=README,
      url="http://doc.devpi.net",
      version='2.2.2.dev0',
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
        ] + [
            ("Programming Language :: Python :: %s" % x) for x in
                "2.7 3.4".split()],
      install_requires=install_requires,
      extras_require=extras_require,
      entry_points = {
        'console_scripts':
                    ["devpi-server = devpi_server.main:main"],
        'devpi_server': [
            "devpi-server-auth-basic = devpi_server.auth_basic",
            "devpi-server-auth-devpi = devpi_server.auth_devpi"]})
