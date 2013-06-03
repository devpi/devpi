

def test_simple_install_process(create_and_upload,
                                create_venv, cmd_devpi, capfd):
    create_and_upload("example-1.2.3")
    create_venv()
    out, err = capfd.readouterr()
    cmd_devpi("install", "example", "-l")
    out, err = capfd.readouterr()
    assert "example==1.2.3" in out

