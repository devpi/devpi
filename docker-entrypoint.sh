#!/bin/bash

function defaults {
    : ${DEVPISERVER_SERVERDIR="/data/server"}
    : ${DEVPI_CLIENTDIR="/data/client"}
    : ${DEVPISERVER_SECRET="/data/devpi.secret"}

    echo "DEVPISERVER_SERVERDIR is ${DEVPISERVER_SERVERDIR}"
    echo "DEVPISERVER_SECRET is ${DEVPISERVER_SECRET}"
    echo "DEVPI_CLIENTDIR is ${DEVPI_CLIENTDIR}"

    export DEVPISERVER_SERVERDIR DEVPISERVER_SECRET DEVPI_CLIENTDIR
}

function initialize_devpi {
    mkdir -p $DEVPISERVER_SERVERDIR
    mkdir -p $DEVPI_CLIENTDIR
    devpi-init --role auto --root-passwd="${DEVPI_PASSWORD}" --serverdir $DEVPISERVER_SERVERDIR

}

defaults

if [ "$1" = 'devpi' ]; then
    if [ ! -f $DEVPISERVER_SECRET ]; then
        su-exec devpi devpi-gen-secret --secretfile $DEVPISERVER_SECRET
    fi
    if [ ! -f  $DEVPISERVER_SERVERDIR/.serverversion ]; then
        export -f initialize_devpi
        su-exec devpi bash -c initialize_devpi
        unset initialize_devpi
    fi

    exec su-exec devpi devpi-server --restrict-modify root --host 0.0.0.0 --port $DEVPI_PORT --secretfile $DEVPISERVER_SECRET
fi

exec "$@"
