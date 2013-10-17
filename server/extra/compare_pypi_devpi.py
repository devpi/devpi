#!/usr/bin/env python
"""
This is a simple web "crawler" that fetches a bunch of urls using a pool to
control the number of outbound connections. It has as many simultaneously open
connections as coroutines in the pool.

The prints in the body of the fetch function are there to demonstrate that the
requests are truly made in parallel.
"""
import sys
import eventlet
from eventlet.green import urllib2
import posixpath
from bs4 import BeautifulSoup
import py

def verify_name(name):
    return Result(name)

class Result:
    def __init__(self, name):
        self.name = name
        self.pypi_url = "https://pypi.python.org/simple/%s/" % name
        self.devpi_url = "http://localhost:3141/root/pypi/+simple/%s/" % name
        self.retrieve("pypi_url")
        self.retrieve("devpi_url")

    def retrieve(self, urlattr):
        bodyattr = urlattr.replace("url", "body")
        url = getattr(self, urlattr)
        fatal_path = logbase.join("res", self.name,
                                  urlattr.replace("url", "fatal"))
        try:
            bodyval = urllib2.urlopen(url).read()
            setattr(self, bodyattr, bodyval)
        except Exception as e:
            if urlattr.startswith("pypi") and "Error 404" in str(e):
                tw.line("%s: pypi request gave 404, project is gone" %
                        self.name)
                # set empty body so compare_links is happy
                bodyval = ""
                setattr(self, bodyattr, bodyval)
            else:
                setattr(self, bodyattr, e)
                fatal_path.ensure().write(str(e))
                return
        logbase.join("res", self.name, bodyattr).ensure().write(
                    str(bodyval))
        if fatal_path.check():
            fatal_path.remove()


    def compare_links(self):
        ret = False
        if isinstance(self.devpi_body, Exception):
            tw.line("%s: devpi request failed: %s" %
                    (self.name, self.devpi_body), red=True)
            ret = True
        if isinstance(self.pypi_body, Exception):
            tw.line("%s: pypi request failed: %s" %
                    (self.name, self.pypi_body), red=True)
            ret = True
        if ret:
            return

        pypi_links = BeautifulSoup(self.pypi_body).findAll("a")
        devpi_links = BeautifulSoup(self.devpi_body).findAll("a")
        misses = []
        count = 0
        pypi_basenames = set()
        for link in pypi_links:
            href = link.get("href")
            if href.startswith("../../packages"):
                count += 1
                # stored at pypi, should appear directly with devpi
                package_prefix = href[6:]
                pypi_basenames.add(posixpath.basename(href))
                #print package_prefix
                for link2 in devpi_links:
                    #print "   ", link2.get("href")
                    if link2.get("href").endswith(package_prefix):
                        break
                else:
                    misses.append((href))
        b = logbase.join("res", self.name).ensure(dir=1)
        misses_path = b.join("devpi_misses")
        if misses:
            tw.line("%s: devpi misses %d out of %d links" %
                    (self.name, len(misses), count), red=True)
            misses_path.write("\n".join(misses))
        else:
            if misses_path.check():
                misses_path.remove()
            extralinks = []
            for link2 in devpi_links:
                devpi_basename = posixpath.basename(link2.get("href"))
                if devpi_basename not in pypi_basenames:
                    extralinks.append(devpi_basename)
            if extralinks:
                extra = ", externally scraped: %s" % (extralinks)
            else:
                extra = ""

            tw.line("%s: devpi has %d pypi internal links%s" %
                    (self.name, count, extra), green=True)
        b.join("pypi_body").write(self.pypi_body)
        b.join("devpi_body").write(self.devpi_body)

    def __repr__(self):
        return "<Result %s>" % self.name

def get_names():
    listfile = logbase.join("simplelist")
    if listfile.check():
        return listfile.readlines(cr=0)
    try:
        from xmlrpc.client import ServerProxy
    except ImportError:
        # PY2
        from xmlrpclib import ServerProxy
    proxy = ServerProxy("https://pypi.python.org/pypi")
    tw.line("getting simple list")
    d = proxy.list_packages_with_serial()
    names = sorted(list(d))
    listfile.write("\n".join(names))
    return names

if __name__ == "__main__":
    tw = py.io.TerminalWriter()
    logbase = py.path.local("/home/hpk/tmp/logcrawl").ensure(dir=1)
    if sys.argv[1] == "all":
        names = get_names()
        tw.line("got %d names" % len(names))
    elif sys.argv[1] in ("devpi_misses", "devpi_fatal"):
        names = []
        for path in logbase.visit(sys.argv[1]):
            names.append(path.dirpath().basename)
        tw.line("working on %d names (previous %s)" % (len(names), sys.argv[1]))
    else:
        raise SystemExit("need to specify type")

    pool = eventlet.GreenPool(50)
    for res in pool.imap(verify_name, names):
        res.compare_links()
