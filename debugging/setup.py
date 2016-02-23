from setuptools import setup


setup(
    name="devpi-debugging",
    description="devpi-debugging: a debugging view for devpi-server",
    url="http://doc.devpi.net",
    version='0.1.0',
    license="MIT",
    entry_points={
        'devpi_server': [
            "devpi-debugging = devpi_debugging.main"]},
    install_requires=[
        'devpi-common',
        'devpi-server<3dev',
        'devpi-web<3dev'],
    include_package_data=True,
    zip_safe=False,
    packages=['devpi_debugging'])
