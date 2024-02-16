def pytest_addoption(parser):
    parser.addoption(
        "--devpi-server-storage-backend", action="store",
        help="run tests with specified dotted name backend")
