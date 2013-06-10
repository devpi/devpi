

def test_simple_install_venv_workflow(create_and_upload,
                                create_venv, out_devpi):
    create_and_upload("example-1.2.3")
    venvdir = create_venv()
    res = out_devpi("install", "--venv", venvdir, "example")
    assert res.ret == 0
    res = out_devpi("install", "--venv", venvdir, "-l")
    out = res.stdout.str()
    assert "example" in out and "1.2.3" in out

