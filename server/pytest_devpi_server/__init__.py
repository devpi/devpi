def pytest_addoption(parser):
    parser.addoption(
        "--slow", action="store_true", default=False,
        help="run slow tests involving remote services (pypi.org)")
    parser.addoption(
        "--backend", action="store",
        help="run tests with specified dotted name backend")
