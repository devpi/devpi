

master bootstrap startup:

    read name2serials from pypi and store it in .pypi_name2serials
                                                .pypi_current_serial
    keep name2serials in RAM
    async: ask changelog API and update name2serials in RAM and write
    it out to .pypi_name2serials/.pypi_current_serial (slow but doesn't matter)
    also mark PYPILINKS/{NAME} cache as dirty for affected packages

master further startups:
    read name2serials from .pypi_name2serials

replica bootstrap startup:
    read name2serials data structure from master into RAM
    write to .pypi_name2serials  / pypi_current_serial
    events: if PYPILINKS/{NAME} is invalidated possibly name2serials

replica further startups:
    read name2serials data structure from .pypi_name2serials
    events: if PYPILINKS/{NAME} is invalidated update name2serials


