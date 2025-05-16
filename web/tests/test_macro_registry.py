def test_macros(dummyrequest, pyramidconfig):
    pyramidconfig.include("pyramid_chameleon")
    pyramidconfig.include("devpi_web.macroregistry")
    pyramidconfig.scan("devpi_web.macros")
    macros = dummyrequest.registry["macros"]
    assert {k: macros.get_group(k) for k in macros.get_groups()} == {
        "main_footer": [
            "footer_versions",
        ],
        "main_header_top": [
            "logo",
        ],
    }
