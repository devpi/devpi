#!/bin/bash

function defaults {
    : ${DEVPISERVER_SERVERDIR="/data/server"}
    : ${DEVPI_CLIENTDIR="/data/client"}

    echo "DEVPISERVER_SERVERDIR is ${DEVPISERVER_SERVERDIR}"
    echo "DEVPI_CLIENTDIR is ${DEVPI_CLIENTDIR}"

    export DEVPISERVER_SERVERDIR DEVPI_CLIENTDIR
}

function initialize_devpi {
    mkdir -p $DEVPISERVER_SERVERDIR
    mkdir -p $DEVPI_CLIENTDIR
    devpi-server --restrict-modify root --start --host 127.0.0.1 --port 3141 --init
    devpi-server --status
    devpi use http://localhost:3141
    devpi login root --password=''
    devpi user -m root password="${DEVPI_PASSWORD}"
    devpi index -y -c public pypi_whitelist='*'
    devpi-server --stop
    devpi-server --status
}

defaults

if [ "$1" = 'devpi' ]; then
    if [ ! -f  $DEVPISERVER_SERVERDIR/.serverversion ]; then
        export -f initialize_devpi
        su-exec devpi bash -c initialize_devpi
        unset initialize_devpi
    fi

    exec su-exec devpi devpi-server --restrict-modify root --host 0.0.0.0 --port $DEVPI_PORT
fi

exec "$@"
