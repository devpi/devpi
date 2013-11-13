from __future__ import unicode_literals
import sys
import os
import json
import py
import subprocess
import logging
from devpi_common.validation import normalize_name
from devpi_common.metadata import Version, splitbasename, BasenameMeta
from devpi_server.main import fatal, server_version
from devpi_server.venv import create_server_venv
import devpi_server


def do_upgrade(xom):
    tw = py.io.TerminalWriter()
    serverdir = xom.config.serverdir
    exportdir = serverdir + "-export"
    if exportdir.check():
        tw.line("removing exportdir: %s" % exportdir)
        exportdir.remove()
    newdir = serverdir + "-import"
    script = sys.argv[0]
    def rel(p):
        return py.path.local().bestrelpath(p)
    state_version = xom.get_state_version()
    tw.sep("-", "exporting to %s" % rel(exportdir))
    if Version(state_version) > Version(server_version):
        fatal("%s has state version %s which is newer than what we "
              "can handle (%s)" %(
                xom.config.serverdir, state_version, server_version))
    elif Version(state_version) < Version(server_version):
        tw.line("creating server venv %s ..." % state_version)
        tmpdir = py.path.local.make_numbered_dir("devpi-upgrade")
        venv = create_server_venv(tw, state_version, tmpdir)
        tw.line("server venv %s created: %s" % (server_version, tmpdir))
        venv.check_call(["devpi-server",
                         "--serverdir", str(serverdir),
                         "--export", str(exportdir)])
    else:
        #tw.sep("-", "creating venv" % rel(exportdir))
        subprocess.check_call([sys.executable, script,
                               "--serverdir", str(serverdir),
                               "--export", str(exportdir)])
    tw.sep("-", "importing from %s" % rel(exportdir))
    tw.line("importing into server version: %s" % server_version)
    subprocess.check_call([sys.executable, script,
                           "--serverdir", str(newdir),
                           "--import", str(exportdir)])
    tw.sep("-", "replacing serverstate")
    backup_dir = serverdir + "-backup"
    if backup_dir.check():
        tw.line("backup dir exists, not creating backup", bold=True)
    else:
        tw.line("moving serverstate to backupdir: %s" % (backup_dir), bold=True)
        serverdir.move(backup_dir)
    if serverdir.check():
        tw.line("removing serverstate: %s" % (serverdir))
        serverdir.remove()
    tw.line("copying new serverstate to serverdir", bold=True)
    newdir.move(serverdir)
    serverdir.join(".serverversion").read()
    tw.line("cleanup: removing exportdir: %s" % exportdir)
    tw.line("have fun serving the new state :)")
    exportdir.remove()

def do_export(path, xom):
    path = py.path.local(path)
    tw = py.io.TerminalWriter()
    if path.check() and path.listdir():
        fatal("export directory %s must not exist or be empty" % path)
    path.ensure(dir=1)
    tw.line("creating %s" % path)
    dumper = Exporter(tw, xom)
    dumper.dump_all(path)
    return 0

def do_import(path, xom):
    logging.basicConfig(level=logging.INFO, format='%(message)s')
    path = py.path.local(path)
    tw = py.io.TerminalWriter()

    if not path.check():
        fatal("path for importing not found: %s" %(path))

    if not xom.db.is_empty():
        fatal("serverdir must not contain users or stages: %s" %
              xom.config.serverdir)
    importer = Importer(tw, xom)
    importer.import_all(path)
    return 0


class Exporter:
    DUMPVERSION = "2"
    def __init__(self, tw, xom):
        self.tw = tw
        self.config = xom.config
        self.db = xom.db
        self.keyfs = xom.keyfs
        self.filestore = xom.filestore

        self.export = {}
        self.export_users = self.export["users"] = {}
        self.export_indexes = self.export["indexes"] = {}

    def copy_file(self, source, dest):
        dest.dirpath().ensure(dir=1)
        source.copy(dest)
        self.tw.line("copied %s to %s" %(source, dest.relto(self.basepath)))
        return dest.relto(self.basepath)

    def warn(self, msg):
        self.tw.line(msg, red=True)

    def completed(self, msg):
        self.tw.line("dumped %s" % msg, bold=True)

    def dump_all(self, path):
        self.basepath = path
        self.export["dumpversion"] = self.DUMPVERSION
        self.export["pythonversion"] = list(sys.version_info)
        self.export["devpi_server"] = devpi_server.__version__
        self.export["secret"] = self.config.secret
        self.compute_global_projectname_normalization()
        for username in self.db.user_list():
            userdir = path.join(username)
            data = self.db.user_get(username, credentials=True)
            indexes = data.pop("indexes", {})
            self.export_users[username] = data
            self.completed("user %r" % username)
            for indexname, indexconfig in indexes.items():
                stage = self.db.getstage(username, indexname)
                if stage.ixconfig["type"] == "mirror":
                    continue
                indexdir = userdir.ensure(indexname, dir=1)
                IndexDump(self, stage, indexdir).dump()
        self._write_json(path.join("dataindex.json"), self.export)

    def compute_global_projectname_normalization(self):
        self.tw.line("computing global projectname normalization map")

        norm2maxversion = {}
        # compute latest normname version across all stages
        for username in self.db.user_list():
            user = self.db.user_get(username)
            for indexname in user.get("indexes", []):
                stage = self.db.getstage(username, indexname)
                names = stage.getprojectnames_perstage()
                for name in names:
                    # pypi names take precedence for defining the realname
                    if stage.name == "root/pypi":
                        version = Version("999999.99999")
                        version.realname = name
                        norm2maxversion[normalize_name(name)] = version
                        continue
                    config = stage.get_projectconfig_perstage(name)
                    if config:
                        maxver = None
                        for ver, verdata in config.items():
                            version = Version(ver)
                            version.realname = verdata.get("name", name)
                            if maxver is None or version > maxver:
                                maxver = version
                        if not maxver:
                            continue
                        norm = normalize_name(name)
                        normver = norm2maxversion.setdefault(norm, maxver)
                        if maxver > normver:
                            norm2maxversion[norm] = maxver

        # determine real name of a project
        self.norm2name = norm2name = {}
        for norm, maxver in norm2maxversion.items():
            norm2name[norm] = maxver.realname

    def get_real_projectname(self, name):
        norm = normalize_name(name)
        return self.norm2name[norm]

    def _write_json(self, path, data):
        writedata = json.dumps(data, indent=2)
        path.dirpath().ensure(dir=1)
        self.tw.line("writing %s, length %s" %(path.relto(self.basepath),
                                               len(writedata)))
        path.write(writedata)


class IndexDump:
    def __init__(self, exporter, stage, basedir):
        self.exporter = exporter
        self.stage = stage
        self.basedir = basedir
        indexmeta = exporter.export_indexes[stage.name] = {}
        indexmeta["projects"] = {}
        indexmeta["indexconfig"] = stage.ixconfig
        indexmeta["files"] = []
        self.indexmeta = indexmeta

    def dump(self):
        for name in self.stage.getprojectnames_perstage():
            data = self.stage.get_projectconfig_perstage(name)
            realname = self.exporter.get_real_projectname(name)
            projconfig = self.indexmeta["projects"].setdefault(realname, {})
            projconfig.update(data)
            assert "+files" not in data
            for version, versiondata in data.items():
                if not version:
                    continue
                versiondata["name"] = realname
                self.dump_releasefiles(realname, versiondata)
                fil = self.stage.get_doczip(name, version)
                if fil:
                    self.dump_docfile(realname, version, fil)
        self.exporter.completed("index %r" % self.stage.name)

    def dump_releasefiles(self, projectname, versiondata):
        files = versiondata.pop("+files", {})
        for basename, file in files.items():
            entry = self.exporter.filestore.getentry(file)
            file_meta = entry._mapping
            assert entry.iscached(), entry.FILE.filepath
            rel = self.exporter.copy_file(
                entry.FILE.filepath,
                self.basedir.join(projectname, entry.basename))
            self.add_filedesc("releasefile", projectname, rel,
                               version=versiondata["version"],
                               entrymapping=file_meta)
            self.dump_attachments(entry)

    def add_filedesc(self, type, projectname, relpath, **kw):
        assert self.exporter.basepath.join(relpath).check()
        d = kw.copy()
        d["type"] = type
        d["projectname"] = projectname
        d["relpath"] = relpath
        self.indexmeta["files"].append(d)
        self.exporter.completed("%s: %s " %(type, relpath))

    def dump_attachments(self, entry):
        basedir = self.exporter.basepath.join("attach", entry.md5)
        filestore = self.exporter.filestore
        for type in filestore.iter_attachment_types(md5=entry.md5):
            for i, attachment in enumerate(filestore.iter_attachments(
                    md5=entry.md5, type=type)):
                data = json.dumps(attachment)
                p = basedir.ensure(type, str(i))
                p.write(data)
                basedir.ensure(type, str(i)).write(data)
                self.exporter.completed("wrote attachment %s [%s]" %
                                 (p.relto(self.basedir), entry.basename))

    def dump_docfile(self, projectname, version, fil):
        p = self.basedir.join("%s-%s.doc.zip" %(projectname, version))
        with p.open("wb") as f:
            f.write(fil.read())
        relpath = p.relto(self.exporter.basepath)
        self.add_filedesc("doczip", projectname, relpath, version=version)

class Importer:
    def __init__(self, tw, xom):
        self.tw = tw
        self.xom = xom
        self.db = xom.db
        self.filestore = xom.filestore
        self.tw = tw

    def read_json(self, path):
        self.tw.line("reading json: %s" %(path,))
        return json.loads(path.read())

    def warn(self, msg):
        self.tw.line(msg, red=True)

    def import_all(self, path):
        self.import_rootdir = path
        self.import_data = self.read_json(path.join("dataindex.json"))
        self.dumpversion = self.import_data["dumpversion"]
        if self.dumpversion not in ("1", "2"):
            fatal("incompatible dumpversion: %r" %(self.dumpversion,))
        self.import_users = self.import_data["users"]
        self.import_indexes = self.import_data["indexes"]
        self.xom.config.secret = secret = self.import_data["secret"]
        self.xom.config.secretfile.write(secret)

        # first create all users
        for user, userconfig in self.import_users.items():
            self.db._user_set(user, userconfig)

        # memorize index inheritance structure
        tree = IndexTree()
        tree.add("root/pypi")  # a root index
        for stagename, import_index in self.import_indexes.items():
            bases = import_index["indexconfig"].get("bases")
            tree.add(stagename, bases)

        # create stages in inheritance/root-first order
        stages = []
        for stagename in tree.iternames():
            if stagename == "root/pypi":
                assert self.db.index_exists(stagename)
                continue
            import_index = self.import_indexes[stagename]
            indexconfig = import_index["indexconfig"]
            stage = self.db.create_stage(stagename, None, **indexconfig)
            stages.append(stage)
        del tree

        # create projects and releasefiles for each index
        for stage in stages:
            assert stage.name != "root/pypi"
            import_index = self.import_indexes[stage.name]
            projects = import_index["projects"]
            #normalized = self.normalize_index_projects(projects)
            for project, versions in projects.items():
                for version, versiondata in versions.items():
                    assert "+files" not in versiondata
                    if not versiondata.get("version"):
                        name = versiondata["name"]
                        self.warn("%r: ignoring project metadata without "
                                  "version information. " % name)
                        continue
                    stage.register_metadata(versiondata)

            # import release files
            for filedesc in import_index["files"]:
                self.import_filedesc(stage, filedesc)

    def import_filedesc(self, stage, filedesc):
        assert stage.ixconfig["type"] != "mirror"
        rel = filedesc["relpath"]
        projectname = filedesc["projectname"]
        p = self.import_rootdir.join(rel)
        assert p.check(), p
        if filedesc["type"] == "releasefile":
            mapping = filedesc["entrymapping"]
            if self.dumpversion == "1":
                # previous versions would not add a version attribute
                version = BasenameMeta(p.basename).version
            else:
                version = filedesc["version"]
            entry = stage.store_releasefile(projectname, version,
                        p.basename, p.read("rb"),
                        last_modified=mapping["last_modified"])
            assert entry.md5 == mapping["md5"]
            assert entry.size == mapping["size"]
            self.import_attachments(entry.md5)
        elif filedesc["type"] == "doczip":
            basename = os.path.basename(rel)
            name, version, suffix = splitbasename(basename)
            stage.store_doczip(name, version, p.open("rb"))
        else:
            fatal("unknown file type: %s" % (type,))

    def import_attachments(self, md5):
        md5dir = self.import_rootdir.join("attach", md5)
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

