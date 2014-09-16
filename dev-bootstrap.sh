#!/usr/bin/env bash

for i in common client server web ; do
    pip uninstall -y devpi-$i
    pip uninstall -y devpi-$i
done
for i in common client server web ; do
    (cd $i ; pip install -e .)
done

# install some deps for testing
pip install -U pytest mock webtest pytest-capturelog pytest-timeout beautifulsoup4 tox
