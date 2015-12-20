import re


def test_simple_install_venv_workflow(create_and_upload,
                                      create_venv, out_devpi):
    create_and_upload("example-1.2.3")
    venvdir = create_venv()
    res = out_devpi("install", "--venv", venvdir, "example")
    assert res.ret == 0
    res = out_devpi("install", "--venv", venvdir, "-l")
    out = res.stdout.str()
    assert "example" in out and "1.2.3" in out


def test_simple_install_venv_workflow_index_option(create_and_upload,
                                                   create_venv,
                                                   devpi, out_devpi):
    create_and_upload("example-1.2.3")
    venvdir = create_venv()

    # remember username
    out = out_devpi("use")
    user = re.search('\(logged in as (.+?)\)', out.stdout.str()).group(1)

    # go to other index
    devpi("use", "root/pypi")

    res = out_devpi(
        "install", "--venv", venvdir, "--index", "%s/dev" % user, "example")
    assert res.ret == 0
    res = out_devpi(
        "install", "--venv", venvdir, "--index", "%s/dev" % user, "-l")
    out = res.stdout.str()
    assert "example" in out and "1.2.3" in out
