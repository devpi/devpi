import itertools
import sys
import json
import os
import py
import logging
import posixpath
import shutil
from devpi_common.validation import normalize_name
from devpi_common.metadata import BasenameMeta
from devpi_common.url import URL
from devpi_server import __version__ as server_version
from devpi_server.model import is_valid_name
from devpi_server.model import get_stage_customizer_classes
from .filestore import Digests
from .filestore import get_hashes
from .main import CommandRunner
from .main import DATABASE_VERSION
from .main import Fatal
from .main import init_default_indexes
from .main import set_state_version
from .main import xom_from_config
from .readonly import get_mutable_deepcopy, ReadonlyView


def has_users_or_stages(xom):
    userlist = xom.model.get_userlist()
    if len(userlist) == 0:
        # no data at all
        return False
    if len(userlist) == 1:
        # we got one user, check to see if it's the default root user
        user, = userlist
        if user.name == "root":
            rootindexes = list(user.get().get("indexes", []))
            if not rootindexes:
                # the root user has no indexes
                return False
            # it's fine if only the default pypi index exists
            if rootindexes == ["pypi"]:
                return False
    return True


def do_export(path, tw, xom):
    path = py.path.local(path)
    if path.check() and path.listdir():
        msg = f"export directory {path} must not exist or be empty"
        raise Fatal(msg)
    path.ensure(dir=1)
    tw.line("creating %s" % path)
    dumper = Exporter(tw, xom)
    with xom.keyfs.read_transaction():
        dumper.dump_all(path)
    return 0


def export(pluginmanager=None, argv=None):
    """ devpi-export command line entry point. """
    if argv is None:
        argv = sys.argv
    else:
        # for tests
        argv = [str(x) for x in argv]
    with CommandRunner(pluginmanager=pluginmanager) as runner:
        parser = runner.create_parser(
            description="Export the data of a devpi-server instance.",
            add_help=False)
        parser.add_help_option()
        parser.add_configfile_option()
        parser.add_logging_options()
        parser.add_storage_options()
        parser.add_export_options()
        parser.add_hard_links_option()
        parser.add_argument("directory")
        config = runner.get_config(argv, parser=parser)
        runner.configure_logging(config.args)
        if not config.nodeinfo_path.exists():
            msg = f"The path '{config.server_path}' contains no devpi-server data, use devpi-init to initialize."
            raise Fatal(msg)
        xom = xom_from_config(config)
        do_export(config.args.directory, runner.tw, xom)
    return runner.return_code or 0


def do_import(path, tw, xom):
    logging.basicConfig(level=logging.INFO, format='%(message)s')
    path = py.path.local(path)

    if not path.check():
        msg = f"path for importing not found: {path}"
        raise Fatal(msg)

    with xom.keyfs.read_transaction():
        if has_users_or_stages(xom):
            msg = f"serverdir must not contain users or stages: {xom.config.server_path}"
            raise Fatal(msg)
    importer = Importer(tw, xom)
    importer.import_all(path)
    if xom.config.args.wait_for_events:
        importer.wait_for_events()
    else:
        importer.warn(
            "Update events have not been processed, when you start the server "
            "they will be processed in order. If you use devpi-web, then the "
            "search index and documentation will gradually update until all "
            "events have been processed.")
    return 0


def import_(pluginmanager=None, argv=None):
    """ devpi-import command line entry point. """
    if argv is None:
        argv = sys.argv
    else:
        # for tests
        argv = [str(x) for x in argv]
    with CommandRunner(pluginmanager=pluginmanager) as runner:
        parser = runner.create_parser(
            description="Import previously exported data into a new devpi-server instance.",
            add_help=False)
        parser.add_help_option()
        parser.add_configfile_option()
        parser.add_logging_options()
        parser.add_storage_options()
        parser.add_init_options()
        parser.add_import_options()
        parser.add_hard_links_option()
        parser.add_argument("directory")
        config = runner.get_config(argv, parser=parser)
        runner.configure_logging(config.args)
        if config.nodeinfo_path.exists():
            msg = f"The path {config.server_path!r} already contains devpi-server data."
            raise Fatal(msg)
        sdir = config.server_path
        if not (sdir.exists() and len(list(sdir.iterdir())) >= 2):
            set_state_version(config, DATABASE_VERSION)
        xom = xom_from_config(config, init=True)
        if config.args.wait_for_events:
            xom.thread_pool.start_one(xom.keyfs.notifier)
        init_default_indexes(xom)
        do_import(config.args.directory, runner.tw, xom)
    return runner.return_code or 0


class Exporter:
    DUMPVERSION = "2"

    def __init__(self, tw, xom):
        self.tw = tw
        self.xom = xom
        self.config = xom.config
        self.filestore = xom.filestore

        self.export = {}
        self.export_users = self.export["users"] = {}
        self.export_indexes = self.export["indexes"] = {}

    def copy_file(self, entry, dest):
        dest.dirpath().ensure(dir=1)
        relpath = dest.relto(self.basepath)
        src = entry.file_os_path()
        if self.config.args.hard_links and src is not None:
            self.tw.line("link file at %s" % relpath)
            os.link(src, dest.strpath)
        elif src is not None:
            self.tw.line("copy file at %s" % relpath)
            shutil.copyfile(src, dest.strpath)
        else:
            self.tw.line("write file at %s" % relpath)
            with open(dest.strpath, 'wb') as df:
                with entry.file_open_read() as sf:
                    shutil.copyfileobj(sf, df)
        return relpath

    def warn(self, msg):
        self.tw.line(msg, yellow=True)

    def completed(self, msg):
        self.tw.line("dumped %s" % msg, bold=True)

    def dump_all(self, path):
        self.basepath = path
        self.export["dumpversion"] = self.DUMPVERSION
        self.export["pythonversion"] = list(sys.version_info)
        self.export["devpi_server"] = server_version
        for user in self.xom.model.get_userlist():
            userdir = path.join(user.name)
            data = user.get(credentials=True)
            indexes = data.pop("indexes", {})
            self.export_users[user.name] = data
            self.completed("user %r" % user.name)
            for indexname, indexconfig in indexes.items():
                stage = self.xom.model.getstage(user.name, indexname)
                IndexDump(self, stage, userdir.join(indexname)).dump()
        self._write_json(path.join("dataindex.json"), self.export)

    def _write_json(self, path, data):
        # use a special handler for serializing ReadonlyViews
        def handle_readonly(val):
            if isinstance(val, ReadonlyView):
                return val._data
            raise TypeError(type(val))

        writedata = json.dumps(data, indent=2, default=handle_readonly)
        path.dirpath().ensure(dir=1)
        self.tw.line(
            f"writing {path.relto(self.basepath)}, length {len(writedata)}")
        path.write(writedata)


class IndexDump:
    def __init__(self, exporter, stage, basedir):
        self.exporter = exporter
        self.stage = stage
        self.basedir = basedir
        self.indexmeta = exporter.export_indexes[stage.name] = {}
        self.indexmeta["indexconfig"] = stage.ixconfig

    def should_dump(self):
        if self.stage.ixconfig["type"] == "mirror":
            if not self.exporter.config.include_mirrored_files:
                return False
        return True

    def dump(self):
        projects = []
        if self.should_dump():
            self.stage.offline = True
            self.indexmeta["projects"] = {}
            self.indexmeta["files"] = []
            projects = self.stage.list_projects_perstage()
        for name in projects:
            data = {}
            versions = self.stage.list_versions_perstage(name)
            for version in versions:
                v = self.stage.get_versiondata_perstage(name, version)
                data[version] = get_mutable_deepcopy(v)
            for val in data.values():
                val.pop("+elinks", None)
            norm_name = normalize_name(name)
            assert norm_name not in self.indexmeta["projects"]
            self.indexmeta["projects"][norm_name] = data

            for version in data:
                vername = data[version]["name"]
                linkstore = self.stage.get_linkstore_perstage(vername, version)
                self.basedir.ensure(dir=1)
                self.dump_releasefiles(linkstore)
                self.dump_toxresults(linkstore)
                entry = None
                if hasattr(self.stage, 'get_doczip_entry'):
                    entry = self.stage.get_doczip_entry(vername, version)
                if entry:
                    self.dump_docfile(vername, version, entry)
        self.exporter.completed("index %r" % self.stage.name)

    def dump_releasefiles(self, linkstore):
        for link in linkstore.get_links(rel="releasefile"):
            entry = self.exporter.filestore.get_file_entry(link.relpath)
            if not entry.last_modified:
                continue
            if not entry.file_exists():
                msg = f"The file for {entry.relpath} is missing."
                raise Fatal(msg)
            relpath = self.exporter.copy_file(
                entry,
                self.basedir.join(linkstore.project, link.version, entry.basename))
            self.add_filedesc("releasefile", linkstore.project, relpath,
                               version=linkstore.version,
                               entrymapping=entry.meta,
                               log=link.get_logs())

    def dump_toxresults(self, linkstore):
        for tox_link in linkstore.get_links(rel="toxresult"):
            reflink = linkstore.stage.get_link_from_entrypath(tox_link.for_entrypath)
            relpath = self.exporter.copy_file(
                tox_link.entry,
                self.basedir.join(linkstore.project, reflink._hash_spec,
                                  tox_link.basename)
            )
            self.add_filedesc(
                type="toxresult",
                project=linkstore.project,
                relpath=relpath,
                version=linkstore.version,
                entrymapping=tox_link.entry.meta,
                for_entrypath=reflink.relpath,
                log=tox_link.get_logs(),
            )

    def add_filedesc(self, type, project, relpath, **kw):
        if not self.exporter.basepath.join(relpath).check():
            msg = f"The file for {relpath} is missing."
            raise Fatal(msg)
        d = kw.copy()
        d["type"] = type
        d["projectname"] = project
        d["relpath"] = relpath
        self.indexmeta["files"].append(d)
        self.exporter.completed(f"{type}: {relpath} ")

    def dump_docfile(self, project, version, entry):
        relpath = self.exporter.copy_file(
            entry,
            self.basedir.join("%s-%s.doc.zip" % (project, version)))
        self.add_filedesc(
            "doczip", project, relpath,
            version=version, entrymapping=entry.meta)


class Importer:
    def __init__(self, tw, xom):
        self.tw = tw
        self.xom = xom
        self.filestore = xom.filestore
        self.tw = tw
        self.index_customizers = get_stage_customizer_classes(self.xom)
        self.types_to_skip = set(self.xom.config.skip_import_type or [])

    def read_json(self, path):
        self.tw.line(f"reading json: {path}")
        return json.loads(path.read())

    def warn(self, msg):
        self.tw.line(msg, yellow=True)

    def display_import_header(self, path):
        self.tw.line("******** Importing packages from %s **********" % path)
        self.tw.line('Number of users: %d' % len(self.import_users))
        self.tw.line('Number of indexes: %d' % len(self.import_indexes))
        total_num_projects = 0
        total_num_files = 0
        for idx_name, idx in self.import_indexes.items():
            num_projects = len(idx.get('projects', {}))
            num_files = len(idx.get('files', []))
            self.tw.line(
                'Index %s has %d projects and %d files'
                % (idx_name, num_projects, num_files))
            total_num_projects += num_projects
            total_num_files += num_files
        self.tw.line('Total number of projects: %d' % total_num_projects)
        self.tw.line('Total number of files: %d' % total_num_files)

    def validate(self, json_path):
        known_types = set(self.index_customizers).union(self.types_to_skip)
        errors = False
        for name in self.import_users:
            if is_valid_name(name):
                continue
            self.xom.log.error(
                "username '%s' contains characters that aren't allowed. "
                "Any ascii symbol besides -.@_ is blocked." % name)
            errors = True
        for index in self.import_indexes:
            config = self.import_indexes[index]['indexconfig']
            index_type = config['type']
            if index_type not in known_types:
                errors = True
                self.xom.log.error(
                    "Unknown index type '%s'. "
                    "Did you forget to install the necessary plugin? "
                    "You can also skip these with '--skip-import-type %s'.",
                    index_type, index_type)
                continue
            if index_type in self.types_to_skip:
                continue
            user, name = index.split('/')
            if is_valid_name(name):
                continue
            self.xom.log.error(
                "indexname '%s' contains characters that aren't allowed. "
                "Any ascii symbol besides -.@_ is blocked." % index)
            errors = True
        if errors:
            self.xom.log.warning(
                "You could also try to edit %s manually to fix the above errors." % json_path)
            raise SystemExit(1)

    def iter_projects_normalized(self, projects):
        project_name_map = {}
        for project in projects:
            project_name_map.setdefault(normalize_name(project), set()).add(project)
        for project, names in project_name_map.items():
            versions = {}
            for name in names:
                versions.update(projects[name])
            yield (project, versions)

    def import_all(self, path):
        self.import_rootdir = path
        json_path = path.join("dataindex.json")
        self.import_data = self.read_json(json_path)
        self.dumpversion = self.import_data["dumpversion"]
        if self.dumpversion not in ("1", "2"):
            msg = f"incompatible dumpversion: {self.dumpversion!r}"
            raise Fatal(msg)
        self.import_users = self.import_data["users"]
        self.import_indexes = self.import_data["indexes"]
        self.display_import_header(path)
        self.validate(json_path)

        # first create all users
        with self.xom.keyfs.write_transaction():
            for username, userconfig in self.import_users.items():
                user = None
                if username == "root":
                    user = self.xom.model.get_user(username)
                if user is None:
                    user = self.xom.model.create_user(username, password="")
                    # missing creation time is set to epoch for regular users
                    userconfig.setdefault("created", "1970-01-01T00:00:00Z")
                user._set(userconfig)

        # memorize index inheritance structure
        tree = IndexTree()
        indexes = set(self.import_indexes)
        with self.xom.keyfs.read_transaction():
            stage = self.xom.model.getstage("root/pypi")
        if stage is not None:
            indexes.add("root/pypi")
            tree.add("root/pypi")
        missing_bases = set()
        for stagename, import_index in self.import_indexes.items():
            bases = import_index["indexconfig"].get("bases")
            if bases is None:
                tree.add(stagename)
            else:
                existing_bases = set(bases).intersection(indexes)
                missing_bases.update(set(bases) - existing_bases)
                tree.add(stagename, existing_bases)

        if missing_bases:
            self.warn(
                "The following indexes are in bases, but don't exist "
                "in the import data: %s" % ", ".join(sorted(missing_bases)))

        # create stages in inheritance/root-first order
        stages = []
        with self.xom.keyfs.write_transaction():
            for stagename in tree.iternames():
                if stagename == "root/pypi" and stagename not in self.import_indexes:
                    continue
                import_index = self.import_indexes[stagename]
                indexconfig = dict(import_index["indexconfig"])
                if indexconfig['type'] in self.types_to_skip:
                    continue
                if 'uploadtrigger_jenkins' in indexconfig:
                    if not indexconfig['uploadtrigger_jenkins']:
                        # remove if not set, so if the trigger was never
                        # used, you don't need to install the plugin
                        del indexconfig['uploadtrigger_jenkins']
                if 'pypi_whitelist' in indexconfig:
                    # this was renamed in 3.0.0
                    whitelist = indexconfig.pop('pypi_whitelist')
                    if 'mirror_whitelist' not in indexconfig:
                        indexconfig['mirror_whitelist'] = whitelist
                user, index = stagename.split("/")
                user = self.xom.model.get_user(user)
                # due to possible circles we create without bases first
                # BBB older versions of devpi had bases for mirror indices,
                # newer versions don't. To support exports from both we
                # have the default None value
                bases = indexconfig.pop('bases', None)
                stage = None
                if stagename == "root/pypi":
                    # see if the stage was already created
                    stage = self.xom.model.getstage(stagename)
                    if self.xom.config.no_root_pypi:
                        continue
                if stage is None:
                    # we create a stage without any config
                    stage = user.create_stage(index, type=indexconfig['type'])
                if stage is not None:
                    # we use modify with _keep_unknown, so data from
                    # removed plugins is preserved
                    stage.modify(**indexconfig, _keep_unknown=True)
                if "bases" in import_index["indexconfig"]:
                    # we are changing bases directly to allow import with
                    # removed bases without changing the data from the export
                    with stage.user.key.update() as userconfig:
                        indexconfig = userconfig['indexes'][stage.index]
                        indexconfig["bases"] = tuple(bases)
                stages.append(stage)
        del tree

        # create projects and releasefiles for each index
        for stage in stages:
            imported_files = set()
            import_index = self.import_indexes[stage.name]
            projects = import_index.get("projects", {})
            files = import_index.get("files", [])
            for project, versions in self.iter_projects_normalized(projects):
                with self.xom.keyfs.write_transaction():
                    for version, versiondata in versions.items():
                        assert "+elinks" not in versiondata
                        versiondata.pop('+doczip', None)
                        versiondata.pop(':action', None)
                        assert not any(True for x in versiondata if x.startswith('+'))
                        if not versiondata.get("version"):
                            name = versiondata["name"]
                            self.warn("%r: version metadata has no explicit "
                                      "version, setting derived %r" %
                                      (name, version))
                            versiondata["version"] = version
                        if hasattr(stage, 'set_versiondata'):
                            stage.set_versiondata(versiondata)
                        else:
                            stage.add_project_name(versiondata["name"])

                    # import release files
                    for filedesc in files:
                        if normalize_name(filedesc["projectname"]) == normalize_name(project):
                            imported_files.add(filedesc["relpath"])
                            self.import_filedesc(stage, filedesc, versions)
            missing = set(x["relpath"] for x in files) - imported_files
            if missing:
                msg = f"Some files weren't imported: {', '.join(sorted(missing))}"
                raise Fatal(msg)

        self.tw.line("********* import_all: importing finished ***********")

    def wait_for_events(self):
        keyfs = self.xom.keyfs
        while True:
            event_serial = keyfs.notifier.read_event_serial()
            latest_serial = keyfs.get_current_serial()
            if event_serial == latest_serial:
                break
            self.tw.line(
                "waiting for events until latest_serial %s" % latest_serial)
            keyfs.notifier.wait_event_serial(latest_serial)
        self.tw.line("wait_for_events: importing finished"
                     "; latest_serial = %s" % latest_serial)

    def import_filedesc(self, stage, filedesc, versions):
        rel = filedesc["relpath"]
        project = filedesc["projectname"]
        p = self.import_rootdir.join(rel)
        if not p.check():
            msg = f"The file at {p} is missing."
            raise Fatal(msg)
        f = p.open("rb")
        if self.xom.config.hard_links:
            # additional attribute for hard links
            f.devpi_srcpath = p.strpath

        # docs and toxresults didn't always have entrymapping in export dump
        mapping = filedesc.get("entrymapping", {})
        hashes = Digests(mapping.get("hashes", {}))
        # devpi-server-2.1 exported with md5 checksums
        if "md5" in mapping:
            hashes["md5"] = mapping["md5"]
        # docs and toxresults didn't always have hashes stored in export dump
        if "hash_spec" in mapping:
            hashes.add_spec(mapping['hash_spec'])
        # note that the actual hash_type used within devpi-server is not
        # determined here but in store_releasefile/store_doczip/store_toxresult etc
        hashes.update(get_hashes(f, hash_types=hashes.get_missing_hash_types()))

        if filedesc["type"] == "releasefile":
            if self.dumpversion == "1":
                # previous versions would not add a version attribute
                version = BasenameMeta(p.basename).version
            else:
                version = filedesc["version"]

            if hasattr(stage, 'store_releasefile'):
                link = stage.store_releasefile(
                    project, version,
                    p.basename, f,
                    hashes=hashes,
                    last_modified=mapping["last_modified"])
                entry = link.entry
            else:  # mirrors
                link = None
                url = URL(mapping['url']).replace(fragment=hashes.best_available_spec)
                entry = self.xom.filestore.maplink(
                    url, stage.username, stage.index, project)
                entry.file_set_content(
                    f, hashes=hashes, last_modified=mapping["last_modified"])
                (_, links_with_data, serial) = stage._load_cache_links(project)
                if links_with_data is None:
                    links_with_data = []
                entrypath = entry.relpath
                if hash_spec := entry.best_available_hash_spec:
                    entrypath = f"{entrypath}#{hash_spec}"
                links = [(url.basename, entrypath)]
                requires_python = [versions[version].get('requires_python')]
                yanked = [versions[version].get('yanked')]
                for key, href, require_python, is_yanked in links_with_data:
                    links.append((key, href))
                    requires_python.append(require_python)
                    yanked.append(is_yanked)
                stage._save_cache_links(
                    project, links, requires_python, yanked, serial, None)
            errors = entry.file_get_hash_errors(hashes)
            if errors:
                # get one error
                error_hash_type = next(iter(errors))
                error_info = errors[error_hash_type]
                digest = error_info['got']
                expected = error_info['expected']
                msg = f"File {p} has bad checksum {digest}, expected {expected}."
                raise Fatal(msg)
        elif filedesc["type"] == "doczip":
            version = filedesc["version"]
            # docs didn't always have entrymapping in export dump
            last_modified = mapping.get("last_modified")
            link = stage.store_doczip(
                project, version, f, hashes=hashes, last_modified=last_modified)
        elif filedesc["type"] == "toxresult":
            linkstore = stage.get_linkstore_perstage(
                filedesc["projectname"], filedesc["version"])
            # we can not search for the full relative path because
            # it might use a different checksum
            basename = posixpath.basename(filedesc["for_entrypath"])
            # toxresults didn't always have entrymapping in export dump
            last_modified = mapping.get("last_modified")
            link, = linkstore.get_links(basename=basename)
            link = stage.store_toxresult(
                link, f, filename=posixpath.basename(filedesc["relpath"]),
                hashes=hashes, last_modified=last_modified)
        else:
            msg = f"unknown file type: {type}"
            f.close()
            raise Fatal(msg)
        if link is not None:
            history_log = filedesc.get('log')
            if history_log is None:
                link.add_log('upload', '<import>', dst=stage.name)
            else:
                link.add_logs(history_log)
        f.close()


class IndexTree:
    """ sort index inheritance structure to that we can
    create in root->child order.
    """
    def __init__(self):
        self.name2children = {}
        self.name2bases = {}

    def add(self, name, bases=None):
        bases = list(bases or [])
        while name in bases:
            bases.remove(name)
        self.name2bases[name] = bases
        if not bases:
            self.name2children.setdefault(None, []).append(name)
        else:
            for base in bases:
                children = self.name2children.setdefault(base, [])
                children.append(name)

    def validate(self):
        all_bases = set(itertools.chain.from_iterable(self.name2bases.values()))
        all_indexes = set(self.name2bases)
        missing = all_bases - all_indexes
        if missing:
            msg = (
                f"The following indexes don't have information in the import "
                f"data: {', '.join(sorted(missing))}")
            raise Fatal(msg)

    def iternames(self):
        self.validate()
        pending = [None]
        created = set()
        while pending:
            name = pending.pop(0)
            for base in self.name2bases.get(name, []):
                if base not in created:
                    pending.append(name)
                    break
            else:
                if name not in created:
                    if name:
                        yield name
                    created.add(name)
                    for child in self.name2children.get(name, []):
                        if child not in created:
                            pending.append(child)
        missed = set(self.name2bases) - created
        if missed:
            msg = (
                f"The following stages couldn't be reached by the dependency "
                f"tree built from the bases: {', '.join(sorted(missed))}")
            raise Fatal(msg)
