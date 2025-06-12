from __future__ import annotations

from devpi_common.types import cached_property
from devpi_server.log import threadlog as log
from devpi_web.compat import tomllib
from pathlib import Path
from pyramid.events import BeforeRender
from pyramid.exceptions import ConfigurationError
from pyramid.interfaces import IRendererFactory
from pyramid.renderers import RendererHelper
from pyramid.renderers import get_renderer
from pyramid.util import TopologicalSorter
from pyramid.util import is_nonstr_iter
import attrs
import os
import venusian
import warnings


@attrs.define(frozen=True)
class GroupDef:
    name: str
    after: None | str = attrs.field(default=None)
    before: None | str = attrs.field(default=None)


class MacroGroup:
    def __init__(self, name, macros, debug):
        self.debug = debug
        self.macros = macros
        self.name = name

    def include(self, __stream, econtext, rcontext, *args, **kw):  # noqa: PYI063
        if self.debug:
            __stream.append(f"<!-- {self.name} macro group start -->")
        for macro in self.macros:
            macro.include(__stream, econtext, rcontext, *args, **kw)
        if self.debug:
            __stream.append(f"<!-- {self.name} macro group end -->")


class MacroResult:
    def __init__(self, macro, *args, **kw):
        self.macro = macro
        self.args = args
        self.kw = kw

    def call(self, request):
        return self.macro.callable(request, *self.args, **self.kw)

    def include(self, __stream, econtext, rcontext, *args, **kw):  # noqa: PYI063
        econtext = econtext.copy()
        request = econtext.get("request")
        if request is None:
            # we might be in a deform template
            field = econtext.get("field")
            if field is not None:
                request = field.view.request
        econtext.update(self.call(request))
        if self.macro.debug:
            __stream.append(f"<!-- {self.macro.name} macro start -->")
        result = self.macro.template.include(__stream, econtext, rcontext, *args, **kw)
        if self.macro.debug:
            __stream.append(f"<!-- {self.macro.name} macro end -->")
        return result


class Macro:
    def __init__(self, func, name, renderer, template, attr, debug, new_name):
        self.debug = debug
        self.func = func
        self.name = name
        self.new_name = new_name
        self.renderer = renderer
        self._template = template
        self.attr = attr

    @cached_property
    def callable(self):
        func = self.func
        if self.attr is not None:
            func = getattr(func, self.attr)
        return func

    def include(self, __stream, econtext, rcontext, *args, **kw):  # noqa: PYI063
        macroresult = MacroResult(self)
        macroresult.include(__stream, econtext, rcontext, *args, **kw)

    def render(self, request, *args, **kw):
        result = self(*args, **kw)
        renderer = result.template(request)
        econtext = dict(request=request)
        econtext.update(result.call(request))
        return renderer(**econtext)

    @cached_property
    def template(self):
        if self._template is not None:
            return self._template
        return self.renderer.renderer.template

    def __call__(self, *args, **kw):
        return MacroResult(self, *args, **kw)


class MacroRegistry:
    def __init__(self, *, debug=False):
        self.debug = debug
        self._groups = {}
        self.groups = {}
        self.macros = {}

    def add_legacy_overwrite(self, name, macro):
        if name in self.macros:
            original_name = f"original-{name}"
            if original_name in self.macros:
                raise ValueError(f"Duplicate macro name {original_name!r}")
            self.macros[original_name] = self.macros[name]
        self.macros[name] = macro

    def register(
        self, obj, name, template, renderer, attr, deprecated, groups, legacy_name
    ):
        # getting the renderer from the RendererHelper reifies it,
        # so we fetch it ourself
        factory = renderer.registry.getUtility(IRendererFactory, name=renderer.type)
        if factory is None:
            raise ValueError(f"No such renderer factory {renderer.type}")
        original_renderer = RendererHelper(
            name=f"devpi_web:{template}",
            package=renderer.package,
            registry=renderer.registry,
        )
        if hasattr(self, name):
            raise ValueError(
                f"Can't register macro {name!r}, because MacroRegistry has an attribute with that name"
            )
        if name in self.macros:
            raise ValueError(f"Duplicate macro name {name!r}")
        self.macros[name] = Macro(
            func=obj,
            name=name,
            renderer=renderer,
            template=None,
            attr=attr,
            debug=self.debug,
            new_name=None if deprecated is None else "",
        )
        original_name = f"original_{name}"
        if hasattr(self, original_name):
            raise ValueError(
                f"Can't register macro {original_name!r}, because MacroRegistry has an attribute with that name"
            )
        if original_name in self.macros:
            raise ValueError(f"Duplicate macro name {original_name!r}")
        self.macros[original_name] = Macro(
            func=obj,
            name=original_name,
            renderer=original_renderer,
            template=None,
            attr=attr,
            debug=self.debug,
            new_name=None if deprecated is None else "",
        )
        # reset cache
        self.groups = {}
        if groups is None:
            groups = []
        if not is_nonstr_iter(groups):
            groups = [groups]
        for group in (GroupDef(g) if isinstance(g, str) else g for g in groups):
            if group.name not in self._groups:
                self._groups[group.name] = TopologicalSorter(default_before=None)
            self._groups[group.name].add(
                name, None, after=group.after, before=group.before
            )
        if legacy_name is not None:
            if (
                legacy_macro := self.macros.get(legacy_name)
            ) is not None and isinstance(legacy_macro, Macro):
                raise ValueError(f"Duplicate legacy name {legacy_name!r}")
            self.macros[legacy_name] = Macro(
                func=obj,
                name=legacy_name,
                renderer=renderer,
                template=None,
                attr=attr,
                debug=self.debug,
                new_name=name,
            )

    def get_group(self, group):
        if group not in self.groups:
            try:
                self.groups[group] = [x[0] for x in self._groups[group].sorted()]
            except ConfigurationError as e:
                msg = f"In definition of group {group!r}: {e}"
                raise ConfigurationError(msg) from e
        return self.groups[group]

    def get_groups(self):
        return set(self._groups)

    def render_group(self, group_name):
        return MacroGroup(
            group_name,
            [self[macro_name] for macro_name in self.get_group(group_name)],
            self.debug,
        )

    def __getattr__(self, name):
        if name not in self.macros:
            raise AttributeError(f"No macro called {name!r} registered.")
        self.__dict__[name] = macro = self[name]
        return macro

    def __getitem__(self, name):
        try:
            macro = self.macros[name]
        except KeyError as e:
            raise KeyError(f"No macro called {name!r} registered.") from e
        if not isinstance(macro, Macro):
            original_macro = self.macros.get(f"original-{name}")
            if isinstance(original_macro, Macro):
                basename = os.path.basename(original_macro.template.filename)
                msg = f"The macro {name!r} has been moved to separate {basename!r} template."
                warnings.warn(msg, DeprecationWarning, stacklevel=5)
                if self.debug:
                    log.warning(msg)
        return macro


def add_macro(
    config,
    obj=None,
    name=None,
    template=None,
    attr=None,
    deprecated=None,
    groups=None,
    legacy_name=None,
):
    obj = config.maybe_dotted(obj)

    if name is None:
        name = obj.__name__

    if isinstance(template, str) and not template.endswith(".pt"):
        raise TypeError(f"A macro must use a page template file, not {template!r}.")

    def register():
        renderer = RendererHelper(
            name=template, package=config.package, registry=config.registry
        )
        macro_registry = config.registry["macros"]
        macro_registry.register(
            obj, name, template, renderer, attr, deprecated, groups, legacy_name
        )

    config.action(("macro", name), register)


def add_macros(config):
    def register():
        macro_registry = config.registry["macros"]
        try:
            renderer = get_renderer("templates/macros.pt")
        except ValueError:
            # no macros in theme
            return
        theme_macros = renderer.implementation().macros
        for theme_macro_name in theme_macros.names:
            macro_registry.add_legacy_overwrite(
                theme_macro_name, theme_macros[theme_macro_name]
            )

    config.action(("macros"), register, order=1)


def add_theme(config, theme_path):
    theme_toml = theme_path.joinpath("theme.toml")
    if theme_toml.exists():
        process_theme_toml(config, theme_path, theme_toml)
    # add deprecated macros.pt
    config.add_macros()


def add_renderer_globals(event):
    request = event.get("request")
    if request is None:
        return
    event["macros"] = request.registry["macros"]


def includeme(config):
    config.add_directive("add_macro", add_macro)
    config.add_directive("add_macros", add_macros)
    config.add_subscriber(add_renderer_globals, BeforeRender)
    config.add_request_method(macros, reify=True)
    config.registry["macros"] = MacroRegistry(
        debug=config.registry.get("debug_macros", False)
    )
    if (theme_path := config.registry.get("theme_path")) is not None:
        add_theme(config, Path(theme_path))


def macro_config(
    *,
    name=None,
    template=None,
    attr=None,
    deprecated=None,
    groups=None,
    legacy_name=None,
):
    def wrap(wrapped):
        settings = dict(
            name=name,
            template=template,
            attr=attr,
            deprecated=deprecated,
            groups=groups,
            legacy_name=legacy_name,
        )

        def callback(context, _name, obj):
            config = context.config.with_package(info.module)
            config.add_macro(obj, **settings)

        info = venusian.attach(wrapped, callback, category="pyramid")

        if info.scope == "class" and settings["attr"] is None:
            settings["attr"] = wrapped.__name__

        settings["_info"] = info.codeinfo
        return wrapped

    return wrap


def macros(request):
    # returns macros which may partially be overwritten in a theme
    return request.registry["macros"]


def _empty_macro(request):  # noqa: ARG001
    return {}


def process_theme_toml(config, theme_path, theme_toml):
    with theme_toml.open("rb") as f:
        cfg = tomllib.load(f)
    for name, macro_cfg in cfg.get("macros", {}).items():
        template = macro_cfg.get("template")
        if template is None:
            msg = f"The {name!r} macro from your theme.toml is missing the 'template' setting."
            raise ValueError(msg)
        template_path = theme_path / "templates" / template
        if not template_path.exists():
            msg = f"The template {template_path.relative_to(theme_path)} for the {name!r} macro from your theme.toml does not exist."
            raise ValueError(msg)
        config.add_macro(_empty_macro, name=name, template=str(template_path))
