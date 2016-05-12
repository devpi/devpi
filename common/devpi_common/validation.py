import re
from .types import ensure_unicode

# below code mostly taken from pypi's mini_pkg_resources.py and webui.py
# on 13th Sep 2013 from http://bitbucket.org/pypa/pypi

legal_package_name = re.compile(r"^[a-z0-9\._-]+$", re.IGNORECASE)
safe_filenames = re.compile(r'.+?\.(exe|tar\.gz|bz2|rpm|deb|zip|tgz|egg|dmg|msi|whl)$', re.I)
safe_name_rex = re.compile('[^A-Za-z0-9]+')


def normalize_name(name):
    """Convert an arbitrary string to a standard distribution name

    Any runs of non-alphanumeric/. characters are replaced with a single '-'.
    """
    name = ensure_unicode(name)
    return safe_name_rex.sub('-', name).lower()

def safe_version(version):
    """Convert an arbitrary string to a standard version string

    Spaces become dots, and all other non-alphanumeric characters become
    dashes, with runs of multiple dashes condensed to a single dash.
    """
    version = version.replace(' ','.')
    return safe_name_rex.sub('-', version)

def is_valid_archive_name(filename):
    return safe_filenames.match(filename)

def validate_metadata(data):
    # from https://bitbucket.org/pypa/pypi/src/1e31fd3cc7a72e4aa54a2bd79d50be5c8c0a3b1e/webui.py?at=default#cl-2124

    ''' Validate the contents of the metadata.
    '''
    if not data.get('name', ''):
        raise ValueError('Missing required field "name"')
    if not data.get('version', ''):
        raise ValueError('Missing required field "version"')
    if 'metadata_version' in data:
        #metadata_version = data['metadata_version']
        del data['metadata_version']
    #else:
    #    metadata_version = '1.0'  # default

    # Ensure that package names follow a restricted set of characters.
    # These characters are:
    #     * ASCII letters (``[a-zA-Z]``)
    #     * ASCII digits (``[0-9]``)
    #     * underscores (``_``)
    #     * hyphens (``-``)
    #     * periods (``.``)
    # The reasoning for this restriction is codified in PEP426. For the
    # time being this check is only validated against brand new packages
    # and not pre-existing packages because of existing names that violate
    # this policy.
    if legal_package_name.search(data["name"]) is None:
        raise ValueError("Invalid package name. Names must contain "
                         "only ASCII letters, digits, underscores, "
                         "hyphens, and periods")

    if not data["name"][0].isalnum():
        raise ValueError("Invalid package name. Names must start with "
                         "an ASCII letter or digit")

    if not data["name"][-1].isalnum():
        raise ValueError("Invalid package name. Names must end with "
                         "an ASCII letter or digit")


    # Traditionally, package names are restricted only for
    # technical reasons; / is not allowed because it may be
    # possible to break path names for file and documentation
    # uploads
    if '/' in data['name']:
        raise ValueError("Invalid package name")


    # again, this is a restriction required by the implementation and not
    # mentiond in documentation; ensure name and version are valid for URLs
    if re.search('[<>%#"]', data['name'] + data['version']):
        raise ValueError('Invalid package name or version (URL safety)')

    # disabled some checks
#    # check requires and obsoletes
#    def validate_version_predicates(col, sequence):
#        try:
#            map(versionpredicate.VersionPredicate, sequence)
#        except ValueError, message:
#            raise ValueError, 'Bad "%s" syntax: %s'%(col, message)
#    for col in ('requires', 'obsoletes'):
#        if data.has_key(col) and data[col]:
#            validate_version_predicates(col, data[col])
#
#    # check provides
#    if data.has_key('provides') and data['provides']:
#        try:
#            map(versionpredicate.check_provision, data['provides'])
#        except ValueError, message:
#            raise ValueError, 'Bad "provides" syntax: %s'%message
#
#    # check PEP 345 fields
#    if metadata_version == '1.2':
#        self._validate_metadata_1_2(data)
#
#    # check classifiers
#    if data.has_key('classifiers'):
#        d = {}
#        for entry in self.store.get_classifiers():
#            d[entry['classifier']] = 1
#        for entry in data['classifiers']:
#            if d.has_key(entry):
#                continue
#            raise ValueError, 'Invalid classifier "%s"'%entry

