import os
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


def test_simple_install_activated_venv_workflow(create_and_upload,
                                      create_venv, out_devpi, monkeypatch):
    create_and_upload("example-1.2.3")
    venvdir = create_venv()
    monkeypatch.setenv("VIRTUAL_ENV", venvdir.strpath)
    res = out_devpi("install", "example")
    assert res.ret == 0
    res = out_devpi("install", "-l")
    out = res.stdout.str()
    assert "example" in out and "1.2.3" in out

    installed_folder_found = False
    for root, dirnames, filenames in os.walk(str(venvdir)):
        installed_folder_found |= "example-1.2.3.dist-info" in dirnames
    assert installed_folder_found


def test_simple_install_new_venv_workflow(create_and_upload,
                                          tmpdir, out_devpi, monkeypatch):
    create_and_upload("example-1.2.3")
    venvdir = tmpdir.join('venv')
    res = out_devpi("install", "--venv", venvdir, "example")
    assert res.ret == 0
    res = out_devpi("install", "--venv", venvdir, "-l")
    out = res.stdout.str()
    assert "example" in out and "1.2.3" in out

    installed_folder_found = False
    for root, dirnames, filenames in os.walk(str(venvdir)):
        installed_folder_found |= "example-1.2.3.dist-info" in dirnames
    assert installed_folder_found

def test_simple_install_venv_workflow_index_option(create_and_upload,
                                                   create_venv,
                                                   devpi, out_devpi):
    create_and_upload("example-1.2.3")
    venvdir = create_venv()

    # remember username
    out = out_devpi("use")
    user = re.search(r'\(logged in as (.+?)\)', out.stdout.str()).group(1)

    # go to other index
    devpi("use", "root/pypi")

    res = out_devpi(
        "install", "--venv", venvdir, "--index", "%s/dev" % user, "example")
    assert res.ret == 0
    res = out_devpi(
        "install", "--venv", venvdir, "--index", "%s/dev" % user, "-l")
    out = res.stdout.str()
    assert "example" in out and "1.2.3" in out


def test_requirement_install_venv_workflow_index_option(create_and_upload,
                                                   create_venv,
                                                   devpi, out_devpi):
    create_and_upload("example-1.2.3")
    venvdir = create_venv()

    # remember username
    out = out_devpi("use")
    user = re.search(r'\(logged in as (.+?)\)', out.stdout.str()).group(1)

    # go to other index
    devpi("use", "root/pypi")

    with open("requirements_test.txt", "w") as req_file:
        req_file.write("example==1.2.3")

    res = out_devpi(
        "install", "--venv", venvdir, "--index", "%s/dev" % user, "--requirement", req_file.name)
    assert res.ret == 0
    res = out_devpi(
        "install", "--venv", venvdir, "--index", "%s/dev" % user, "-l")
    out = res.stdout.str()
    assert "example" in out and "1.2.3" in out
