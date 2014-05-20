from setuptools import setup


setup(
    name="devpi-web",
    description="devpi-web: a web view for devpi-server",
    url="http://doc.devpi.net",
    version="0.1",
    maintainer="Holger Krekel",
    maintainer_email="holger@merlinux.eu",
    license="MIT",
    classifiers=[
        "Development Status :: 4 - Beta",
        "Environment :: Web Environment",
        "Intended Audience :: Developers",
        "Intended Audience :: System Administrators",
        "License :: OSI Approved :: MIT License",
        "Programming Language :: Python",
        "Topic :: Internet :: WWW/HTTP",
        "Topic :: Internet :: WWW/HTTP :: WSGI :: Application"] + [
            "Programming Language :: Python :: %s" % x
            for x in "2.7 3.3".split()],
    entry_points={
        'devpi_server': [
            "devpi-web = devpi_web.main"]},
    install_requires=[
        'devpi-server',
        'pyramid',
        'pyramid-chameleon'],
    packages=['devpi_web'])
