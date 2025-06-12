def test_macros(dummyrequest, pyramidconfig):
    pyramidconfig.include("pyramid_chameleon")
    pyramidconfig.include("devpi_web.macroregistry")
    pyramidconfig.scan("devpi_web.macros")
    macros = dummyrequest.registry["macros"]
    assert {k: macros.get_group(k) for k in macros.get_groups()} == {
        "html_head": [
            "favicon",
            "html_head_css",
            "html_head_scripts",
        ],
        "main_footer": [
            "footer_versions",
        ],
        "main_header": [
            "header_status",
        ],
        "main_header_top": [
            "logo",
        ],
        "main_navigation": [
            "status_badge",
        ],
    }
