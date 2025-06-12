from .macroregistry import macro_config


@macro_config(
    template="templates/footer_versions.pt",
    groups="main_footer",
    legacy_name="versions",
)
def footer_versions(request):
    return dict(version_infos=request.registry.get("devpi_version_info"))
