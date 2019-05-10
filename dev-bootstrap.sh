#!/usr/bin/env bash

for i in common client server web ; do
    pip uninstall -y devpi-$i
done
for i in common client server web ; do
    (cd $i ; pip install -U -e .)
done

# install some deps for testing
pip install -U PdbEditorSupport Sphinx pytest mock webtest pytest-cov pytest-flake8 pytest-pdb pytest-timeout beautifulsoup4 tox towncrier wheel
