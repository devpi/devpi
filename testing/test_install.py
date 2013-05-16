

def test_simple_install_process(create_and_upload, pypiserverprocess,
                                create_venv, cmd_devpi):
    create_and_upload("example-1.2.3")
    create_venv()
    cmd_devpi("use", pypiserverprocess.cfg.url)
    result = cmd_devpi("install", "example", "-l")
    result.stdout.fnmatch_lines("""
        example==1.2.3
    """)

def test_install_debug_no_debug(create_venv, pypiserverprocess, cmd_devpi):
    create_venv()
    cmd_devpi("use", pypiserverprocess.cfg.url)
    result = cmd_devpi("install", "--debug", "-l")
    result.stdout.fnmatch_lines("""
        *debug*
    """)
