from devpi.index import index_show, main
import pytest


def test_index_show_empty(loghub):
    with pytest.raises(SystemExit):
        index_show(loghub, None)
    loghub._getmatcher().fnmatch_lines("*no index specified*")


def test_index_show_without_login(loghub, mock_http_api):
    loghub.current.reconfigure(dict(
        simpleindex="http://devpi/index",
        index="http://devpi/root/dev/",
        login="http://devpi/+login"))
    loghub.args.indexname = "hello/dev"
    loghub.args.keyvalues = []
    loghub.args.create = None
    loghub.args.delete = None
    loghub.args.list = None
    loghub.args.no_projects = None
    mock_http_api.set("http://devpi/hello/dev", 200, result={})
    main(loghub, loghub.args)


def test_index_list_without_login(loghub):
    loghub.args.indexname = None
    loghub.args.keyvalues = []
    loghub.args.list = True
    with pytest.raises(SystemExit):
        main(loghub, loghub.args)
    loghub._getmatcher().fnmatch_lines("*no current authenticated user*")


def test_index_list_with_login_and_no_username(loghub, mock_http_api):
    loghub.current.reconfigure(dict(
        simpleindex="http://devpi/index",
        index="http://devpi/root/dev/",
        login="http://devpi/+login"))
    loghub.current.set_auth("hello", "pass1")
    loghub.args.indexname = None
    loghub.args.keyvalues = []
    loghub.args.list = True
    mock_http_api.set("http://devpi/hello", 200, result={
        "username": "hello",
        "indexes": {"foo": None}})
    main(loghub, loghub.args)
    assert list(filter(None, loghub._getmatcher().lines)) == ["hello/foo"]


def test_index_list_with_login_and_username(loghub, mock_http_api):
    loghub.current.reconfigure(dict(
        simpleindex="http://devpi/index",
        index="http://devpi/root/dev/",
        login="http://devpi/+login"))
    loghub.current.set_auth("hello", "pass1")
    loghub.args.indexname = "root"
    loghub.args.keyvalues = []
    loghub.args.list = True
    mock_http_api.set("http://devpi/root", 200, result={
        "username": "root",
        "indexes": {"dev": None}})
    main(loghub, loghub.args)
    assert list(filter(None, loghub._getmatcher().lines)) == ["root/dev"]


def test_index_list_with_login_and_indexname(loghub, mock_http_api):
    loghub.current.reconfigure(dict(
        simpleindex="http://devpi/index",
        index="http://devpi/root/dev/",
        login="http://devpi/+login"))
    loghub.current.set_auth("hello", "pass1")
    loghub.args.indexname = "root/dev"
    loghub.args.keyvalues = []
    loghub.args.list = True
    with pytest.raises(SystemExit):
        main(loghub, loghub.args)
    loghub._getmatcher().fnmatch_lines("*user name contains a slash*")


def test_index_create_requires_user(loghub, mock_http_api):
    loghub.current.reconfigure(dict(
        simpleindex="http://devpi/index",
        index="http://devpi/root/dev/",
        login="http://devpi/+login"))
    loghub.args.indexname = "hello/dev"
    loghub.args.keyvalues = []
    loghub.args.create = True
    loghub.args.delete = None
    loghub.args.list = None
    with pytest.raises(SystemExit):
        main(loghub, loghub.args)
    loghub._getmatcher().fnmatch_lines("*you need to be logged in*")


def test_automatic_user_creation_on_index_create(loghub, mock_http_api):
    loghub.current.reconfigure(dict(
        simpleindex="http://devpi/index",
        index="http://devpi/root/dev/",
        login="http://devpi/+login"))
    loghub.current.set_auth("hello", "pass1")
    loghub.args.indexname = "hello/dev"
    loghub.args.keyvalues = []
    loghub.args.create = True
    loghub.args.delete = None
    loghub.args.list = None
    # only the index should be accessed, if there is anything else, the mocking
    # will throw an error
    mock_http_api.set("http://devpi/hello/dev", 200, result={})
    mock_http_api.set("http://devpi/hello/dev?no_projects=", 200, result={})
    main(loghub, loghub.args)
