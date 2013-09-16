import execnet
import json
import os
import py
import logging

from devpi_server.main import fatal

def do_export(path, xom):
    path = py.path.local(path)
    tw = py.io.TerminalWriter()
    if path.check():
        tw.line("removing %s" % path, red=True)
    path.ensure(dir=1)
    tw.line("creating %s" % path)
    dumper = Exporter(tw, xom)
    dumper.dump_all(path)
    return 0

def do_import(path, xom):
    logging.basicConfig(level="INFO", format='%(message)s')
    path = py.path.local(path)
    tw = py.io.TerminalWriter()

    if not path.check():
        fatal("path for importing not found: %s" %(path))

    dumpversion = path.join("dumpversion").read()
    if dumpversion == "1":
        importer = Importer_1(tw, xom)
    else:
        fatal("incompatible dumpversion: %r" %(dumpversion,))
    entries = xom.keyfs.basedir.listdir()
    if entries:
        offending = [x.basename for x in entries
                        if x.check(dotfile=0)]
        if "root" in offending:
            root = xom.keyfs.basedir.join("root")
            if root.listdir() == [root.join("pypi")]:
                offending.remove("root")
        if offending:
            fatal("serverdir must be empty: %s (found %s)"
                    %(xom.config.serverdir, offending))
    importer.import_all(path)
    return 0

class Exporter:
    DUMPVERSION = "1"
    def __init__(self, tw, xom):
        self.tw = tw
        self.config = xom.config
        self.db = xom.db
        self.keyfs = xom.keyfs
        self.filestore = xom.releasefilestore

    def dump_all(self, path):
        self.basepath = path
        path.join("dumpversion").write(self.DUMPVERSION)
        path.join("secret").write(self.config.secret)
        self.dump_users(path / "users")
        #self.dump_tests(path / "tests")

    def dump_users(self, path):
        users = {}
        for username in self.db.user_list():
            userdir = path.join(username)
            data = self.db.user_get(username, credentials=True)
            users[username] = data
            for indexname, indexconfig in data.get("indexes", {}).items():
                stage = self.db.getstage(username, indexname)
                if stage.ixconfig["type"] != "mirror":
                    indexdir = userdir.ensure(indexname, dir=1)
                    self.dump_stage(indexdir, stage)
        self._write_json(path.join(".config"), users)

    def dump_stage(self, indexdir, stage):
        indexmeta = {"projects": {}, "filemeta": {}}
        for projectname in stage.getprojectnames_perstage():
            data = stage.get_projectconfig_perstage(projectname)
            indexmeta["projects"][projectname] = data
            for version, versiondata in data.items():
                self.dump_releasefiles(indexdir, versiondata, indexmeta)
        self._write_json(indexdir.join(".meta"), indexmeta)

    def dump_releasefiles(self, basedir, versiondata, indexmeta):
        for releasefile in versiondata.get("+files", {}).values():
            entry = self.filestore.getentry(releasefile)
            indexmeta["filemeta"][entry.basename] = entry._mapping
            if entry.iscached():
                self._copy_file(entry.FILE.filepath,
                                basedir.join(entry.basename))
            self.dump_attachments(entry)

    def dump_attachments(self, entry):
        basedir = self.basepath.join("attach", entry.md5)
        for type in self.filestore.iter_attachment_types(md5=entry.md5):
            for i, attachment in enumerate(self.filestore.iter_attachments(
                    md5=entry.md5, type=type)):
                data = json.dumps(attachment)
                p = basedir.ensure(type, str(i))
                p.write(data)
                basedir.ensure(type, str(i)).write(data)
                self.tw.line("wrote attachment %s [%s]" %
                                 (p.relto(self.basepath), entry.basename))

    def _copy_file(self, source, dest):
        source.copy(dest)
        self.tw.line("copied %s to %s" %(source, dest.relto(self.basepath)))

    def _write_json(self, path, data):
        writedata = json.dumps(data, indent=2)
        path.dirpath().ensure(dir=1)
        self.tw.line("writing %s, length %s" %(path.relto(self.basepath),
                                               len(writedata)))
        path.write(writedata)

class Reader_1:
    def __init__(self, tw, path):
        self.tw = tw
        self.path = path
        self.config_users = self.read_json(path.join("users", ".config"))

    def users(self):
        for user, userconfig in self.config_users.items():
            newuserconfig = userconfig.copy()
            indexes = newuserconfig.pop("indexes", None)
            yield user, newuserconfig, indexes

    def indexes(self, user):
        userconfig = self.config_users[user]
        for index, indexconfig in userconfig.get("indexes", {}).items():
            yield index, indexconfig

    def index(self, stagename):
        stagedir = self.path.join("users", stagename)
        return Indexdir_1(stagedir, self.read_json(stagedir.join(".meta")))

    def read_json(self, path):
        self.tw.line("reading json: %s" %(path,))
        return json.loads(path.read("rb"))

class Indexdir_1:
    def __init__(self, path, meta):
        self.path = path
        self.filemeta = meta["filemeta"]
        self.projects = meta["projects"]

class Importer_1:
    def __init__(self, tw, xom):
        self.tw = tw
        self.xom = xom
        self.db = xom.db
        self.filestore = xom.releasefilestore

    def import_all(self, path):
        self.basepath = path
        reader = Reader_1(self.tw, path)
        secret = path.join("secret").read()
        self.xom.config.secretfile.write(secret)
        self.xom.config.secret = secret

        # first create all users, and memorize index inheritance structure
        tree = IndexTree()
        stage2config = {}
        for user, userconfig, indexes in reader.users():
            self.db._user_set(user, userconfig)
            if indexes:
                for index, indexconfig in indexes.items():
                    stagename = "%s/%s" %(user, index)
                    stage2config[stagename] = indexconfig
                    tree.add(stagename, indexconfig.get("bases"))

        # create stages in inheritance/root-first order
        stages = {}
        for stagename in tree.iternames():
            indexconfig = stage2config[stagename]
            stage = self.db.create_stage(stagename, None, **indexconfig)
            stages[stagename] = stage
        del tree

        # create projects and releasefiles
        for stage in stages.values():
            if stage.name == "root/pypi":
                continue
            index = reader.index(stage.name)
            for project, versions in index.projects.items():
                for version, versiondata in versions.items():
                    files = versiondata.pop("+files", [])
                    assert versiondata, (project, version)
                    if hasattr(stage, "register_metadata"):
                        stage.register_metadata(versiondata)
                    for file in files:
                        self.import_file(stage, index, file)

    def import_file(self, stage, index, file):
        p = index.path.join(os.path.basename(file))
        filemeta = index.filemeta.get(file, None)
        assert filemeta
        if stage.ixconfig["type"] != "mirror":
            assert p.check(), p
            entry = stage.store_releasefile(p.basename, p.read("rb"),
                        last_modified=filemeta["last_modified"])
            assert entry.md5 == filemeta["md5"]
            assert entry.size == filemeta["size"]
            self.import_attachments(entry.md5)

    def import_attachments(self, md5):
        md5dir = self.basepath.join("attach", md5)
        if not md5dir.check():
            return
        for type_path in md5dir.listdir():
            type = type_path.basename
            for i in range(len(type_path.listdir())):
                attachment_data = type_path.join(str(i)).read()
                self.import_attachment(md5, type, attachment_data)

    def import_attachment(self, md5, type, attachment_data):
        self.tw.line("importing attachment %s/%s" %(md5, type))
        self.filestore.add_attachment(md5=md5, type=type, data=attachment_data)

class IndexTree:
    """ sort index inheritance structure to that we can
    create in root->child order.
    """
    def __init__(self):
        self.name2children = {}
        self.name2bases = {}

    def add(self, name, bases=None):
        self.name2bases[name] = bases or []
        if not bases:
            self.name2children.setdefault(None, []).append(name)
        else:
            for base in bases:
                children = self.name2children.setdefault(base, [])
                children.append(name)

    def iternames(self):
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
