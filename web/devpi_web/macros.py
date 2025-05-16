from .macroregistry import macro_config


@macro_config(template="templates/footer.pt")
def footer(request):  # noqa: ARG001
    return dict()


@macro_config(
    template="templates/footer_versions.pt",
    groups="main_footer",
    legacy_name="versions",
)
def footer_versions(request):
    return dict(version_infos=request.registry.get("devpi_version_info"))


@macro_config(template="templates/logo.pt", groups="main_header_top")
def logo(request):  # noqa: ARG001
    return dict()


@macro_config(
    template="templates/status_badge.pt",
    groups="main_navigation",
    legacy_name="statusbadge",
)
def status_badge(request):
    return dict(status_info=request.status_info)
