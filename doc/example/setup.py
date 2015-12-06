import os, sys
from distutils.core import setup

if __name__ == '__main__':
    setup(
        name='example',
        description='example test project (please ignore)',
        version='1.0',
        author='Holger Krekel',
        url="http://example.com",
        author_email='holger at merlinux.eu',
        py_modules=["example", "test_example"],
    )
