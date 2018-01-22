import os
import sys
import zipfile


def create_zipfile(name, base):
    zip_file = zipfile.ZipFile(name, "w")
    for root, dirs, files in os.walk(base):
        for name in files:
            if name == '__pycache__':
                continue
            full = os.path.join(root, name)
            relative = root[len(base):].lstrip(os.path.sep)
            dest = os.path.join(relative, name)
            zip_file.write(full, dest)
    zip_file.close()


if __name__ == '__main__':
    name = sys.argv[1]
    base = sys.argv[2]
    tmp_name = "%s.tmp" % name
    try:
        create_zipfile(tmp_name, base)
    except Exception:
        os.remove(tmp_name)
        raise
    finally:
        os.rename(tmp_name, name)
