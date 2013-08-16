import os, sys
from setuptools import setup, Command

from pysober import __version__

def main():
    setup(
        name='pysober',
        description='A insignificant project for the sake of documentation',
        version=__version__,
        author='Holger Krekel',
        author_email='holger at merlinux.eu',
        py_modules=["pysober"],
        zip_safe=False,
    )

if __name__ == '__main__':
    main()
