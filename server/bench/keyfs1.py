import py
from devpi_server.keyfs import KeyFS


def create_dict(keyfs, num):
    key = keyfs.add_key("NAME", "somedir/file", dict)
    for i in range(num):
        with keyfs.transaction():
            key.set({i:i})

def create_files(keyfs, num):
    key = keyfs.add_key("FILES", "somedir/otherfile", bytes)
    content = '1'.encode('utf-8') * 5000000
    for i in range(num):
        with keyfs.transaction():
            key.set(content)
        print "wrote", i

if __name__ == "__main__":
    dir = py.path.local("/tmp/keyfs")
    if dir.exists():
        dir.remove()
    keyfs = KeyFS(dir)
    #create_dict(keyfs, 3000)
    create_files(keyfs, 150)

