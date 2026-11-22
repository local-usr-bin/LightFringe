"""Shared, fail-closed checks for the 2.0 release evidence."""
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import types


class ContractError(RuntimeError):
    pass


def require(condition, message):
    if not condition:
        raise ContractError(message)


def sha(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _unique_fields(pairs):
    record = {}
    for name, value in pairs:
        require(name not in record, f"duplicate JSON key: {name}")
        record[name] = value
    return record


def read_pinned_json(path, expected_sha):
    raw = Path(path).read_bytes()
    require(re.fullmatch(r"[0-9a-f]{64}", expected_sha or "") is not None, "missing external SHA256 pin")
    require(hashlib.sha256(raw).hexdigest() == expected_sha, "pinned JSON SHA256 mismatch")
    value = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_fields)
    require(isinstance(value, dict), "contract must be a JSON object")
    return value


def read_draft(path, expected_sha):
    draft = read_pinned_json(path, expected_sha)
    require(draft["schema"] == "lf-release-draft-v2", "unexpected source anchor schema")
    require(re.fullmatch(r"[0-9a-f]{40}", draft["source_head"]) is not None, "invalid source HEAD")
    require(draft["release_version"] == "2.0.0" and bool(draft["release_build"]), "wrong target release identity")
    return draft


def require_binding(draft, closed, anchor_sha):
    require(closed["source_head"] == draft["source_head"], "source HEAD differs from approved Git anchor")
    require(closed["source_anchor_sha256"] == anchor_sha, "source anchor differs")
    require(all(closed[key] == draft[key] for key in ("release_version", "release_build", "source_baseline")),
            "contract product identity differs from approved anchor")


def require_product(draft, version, build, baseline):
    require((version, build, baseline) ==
            (draft["release_version"], draft["release_build"], draft["source_baseline"]),
            "product identity differs from approved 2.0 source")


def require_window(draft, app_version, title):
    require(app_version == draft["release_version"], "Qt applicationVersion differs")
    expected = f"光纹 LightFringe {draft['release_version']} · {draft['release_build']}"
    require(title == expected, "window title differs from approved identity")


def require_modes(draft, labels, layouts):
    require(list(labels) == [row["label"] for row in draft["modes"]],
            "experiment mode labels or order differ from approved five modes")
    layouts = list(layouts)
    require(len(layouts) == len(draft["array_layouts"]) and dict(layouts) == draft["array_layouts"],
            "multiaperture layouts differ from approved four choices")


def pdf_creator(draft, mode):
    value = f"光纹 LightFringe {draft['release_version']} · 构建 {draft['release_build']}"
    if mode in ("single-slit", "double-slit"):
        value += f" · 核心基线 {draft['source_baseline']}"
    return value


def require_pdf_pages(draft, mode, pages):
    row = next((item for item in draft["modes"] if item["id"] == mode), None)
    require(row is not None and pages in row["pages"], f"unexpected PDF page count: {mode}/{pages}")


def inspect_qt_pdf(draft, mode, data, ledger=None):
    """Bound the known Qt writer format. An independent PDF reader checks page text."""
    require(len(data) > 1000 and data.startswith(b"%PDF-") and data.rstrip().endswith(b"%%EOF"),
            "invalid PDF envelope")
    pages = len(re.findall(rb"/Type\s*/Page(?:\s|/|>)", data))
    require_pdf_pages(draft, mode, pages)
    if mode in ("circular", "multiaperture"):
        require(ledger is not None and ledger.get("pages") == pages, "PDF paint ledger disagrees")
    creator = pdf_creator(draft, mode)
    # Qt 6.8.3 produces the Unicode metadata form from QPdfWriter.
    token = b"/Creator (" + b"\xfe\xff" + creator.encode("utf-16-be") + b")"
    require(data.count(token) == 1, "Qt PDF Creator differs from the approved identity")
    return pages, creator


def require_pdf_readback(draft, mode, creator, texts):
    require_pdf_pages(draft, mode, len(texts))
    expected = pdf_creator(draft, mode)
    require(creator == expected, "readback Creator differs")
    compact = lambda value: "".join(value.split())
    require(all(compact(expected) in compact("\n".join(text.splitlines()[:6])) for text in texts),
            "page header identity differs")


def require_relative(name):
    require(isinstance(name, str), "relative path must be text")
    relative = PurePosixPath(name)
    require(name == relative.as_posix()
            and "\\" not in name and ":" not in name and not relative.is_absolute()
            and relative.parts and all(part not in (".", "..") and part.rstrip(" .") == part
                                       for part in relative.parts), f"unconfined path: {name}")
    return relative


def payload_hashes(root):
    root = Path(root)
    require(root.is_dir() and not (root.is_symlink() or root.is_junction()), "invalid payload root")
    files, seen = {}, set()
    for path in root.rglob("*"):
        require(not path.is_symlink() and not path.is_junction(), f"linked payload path: {path}")
        if path.is_file():
            relative = path.relative_to(root).as_posix()
            require_relative(relative)
            require(relative.casefold() not in seen, f"case collision: {relative}")
            seen.add(relative.casefold())
            files[relative] = sha(path)
    return files


def native_paths(payload):
    return {name for name in payload if Path(name).suffix.lower() in (".dll", ".pyd", ".exe")}


def require_hashes(paths):
    require(isinstance(paths, dict), "expected a relative path/SHA256 map")
    for name, digest in paths.items():
        require_relative(name)
        require(isinstance(digest, str) and re.fullmatch(r"[0-9a-f]{64}", digest) is not None,
                f"missing or invalid SHA256 pin: {name}")
    require(len(paths) == len({name.casefold() for name in paths}), "case collision in pinned path map")


def require_payload(draft, expected, actual, replacement=None):
    require_hashes(expected)
    require(expected == actual, "payload differs from independently pinned file manifest")
    layout = draft["layout"]
    needed = set(layout["required_runtime"]) | set(layout["qt_dlls"]) | {layout["exe"], layout["manual_path"]}
    needed |= set(layout["root_docs"]) | set(layout["source_offer_sha256"])
    needed |= {name for name in layout["historical_locked_inputs_sha256"] if name.startswith("LICENSES/")}
    require(needed <= set(actual), "required Runtime or accompanying files missing")
    plugins = {name for name in native_paths(actual) if "plugins" in name.casefold().split("/")}
    require(plugins == set(layout["qt_plugins"]), "unapproved or missing Qt plugin")
    require({name for name in native_paths(actual) if Path(name).name.casefold().startswith("qt6")}
            == set(layout["qt_dlls"]), "unapproved or missing Qt runtime library")
    require(not any(Path(name).name.casefold() in ("opengl32sw.dll", draft["pe_derivation"]["old_import"])
                    for name in native_paths(actual)), "excluded Mesa or hashed MSVC library found")
    fixed = layout["fixed_payload_sha256"] | layout["source_offer_sha256"]
    fixed |= {name: digest for name, digest in layout["historical_locked_inputs_sha256"].items()
              if name in actual}
    for name, checksum in fixed.items():
        require(actual.get(name) == (replacement or {}).get(name, checksum),
                f"locked input/source hash differs: {name}")


def locked_native_inputs(draft, payload, explicit):
    """Match every third-party PE to a historical or explicitly approved source hash."""
    require_hashes(explicit)
    native = native_paths(payload) - {draft["layout"]["exe"]}
    prior = draft["layout"]["historical_locked_inputs_sha256"]
    missing = {name for name in native if name not in prior}
    require(set(explicit) == missing, "new native inputs lack an independently approved pin")
    provenance = prior | explicit
    for name in native:
        require(payload[name] == provenance[name], f"native input provenance differs: {name}")


def require_embedded_set(draft, names):
    require(isinstance(names, list) and len(names) == len(set(names)), "invalid or duplicate TOC modules")
    required = {"lightfringe", "lightfringe.__main__", "lightfringe.gui", "lightfringe.airy_pdf_gui",
                "lightfringe.multiaperture_gui", "lightfringe.multiaperture_view", "lightfringe.report_layout"}
    required |= {row["writer"] for row in draft["modes"]}
    required |= {f"lightfringe.{Path(name).stem}" for name in draft["science_sources"]}
    require(required <= set(names) <= set(draft["product_sources"]), "embedded module set differs from Git source")


def code_model(value):
    # Preserve the historical deep comparison, omitting only co_filename.
    if isinstance(value, types.CodeType):
        fields = (
            "co_argcount", "co_posonlyargcount", "co_kwonlyargcount", "co_nlocals",
            "co_stacksize", "co_flags", "co_code", "co_consts", "co_names",
            "co_varnames", "co_freevars", "co_cellvars", "co_firstlineno",
            "co_linetable", "co_exceptiontable", "co_name", "co_qualname",
        )
        return {"type": "code", **{name: code_model(getattr(value, name)) for name in fields}}
    if isinstance(value, (tuple, list)):
        return {"type": type(value).__name__, "items": [code_model(x) for x in value]}
    if isinstance(value, frozenset):
        return {"type": "frozenset", "items": sorted((code_model(x) for x in value),
                                                    key=lambda x: json.dumps(x, sort_keys=True))}
    if isinstance(value, bytes):
        return {"type": "bytes", "hex": value.hex()}
    return {"type": type(value).__name__, "repr": repr(value)}


def code_sha(code):
    require(isinstance(code, types.CodeType), "loader did not return product code")
    return hashlib.sha256(json.dumps(code_model(code), sort_keys=True, ensure_ascii=True).encode()).hexdigest()


def require_frozen_module(draft, closed, name, module, runtime):
    entry = draft["product_sources"][name]
    expected = (Path(runtime) / entry["path"]).resolve()
    spec = module.__spec__
    loader = module.__loader__
    require(spec is not None and spec.name == module.__name__ == name and spec.loader is loader,
            f"unbound module spec: {name}")
    require(spec.origin and module.__file__ and Path(spec.origin).resolve() ==
            Path(module.__file__).resolve() == expected, f"module origin outside approved Runtime: {name}")
    require(type(loader).__module__ == "pyimod02_importers" and type(loader).__name__ == "PyiFrozenLoader",
            f"unexpected frozen loader: {name}")
    require(code_sha(loader.get_code(name)) == closed["embedded_code_sha256"][name],
            f"runtime product code differs: {name}")
    return {"module": name, "origin": str(expected), "git_blob": entry["git_blob"],
            "code_sha256": closed["embedded_code_sha256"][name]}


def require_closed(draft, closed, anchor_sha, bundle, mode):
    require(closed["schema"] == "lf-release-closure-v2" and closed["state"] == "ASSEMBLY_VERIFIED",
            "E2 assembly closure is incomplete")
    require_binding(draft, closed, anchor_sha)
    require(closed["diagnostic_variant"] == mode, "wrong diagnostic variant")
    paths = closed["payload_sha256"]
    replacement = {}
    if mode == "control":
        require(closed["replacement_markers"] == closed["replacement_native"] == [],
                "control cannot authorize replacements")
        locked_native_inputs(draft, paths, closed["new_native_pins"])
    elif mode == "replacement":
        layout = draft["layout"]
        prior = closed["control_payload_sha256"]
        locked_native_inputs(draft, prior, closed["new_native_pins"])
        require_payload(draft, prior, prior)
        native = {row["relative"]: row for row in closed["replacement_native"]}
        require(len(closed["replacement_native"]) == 3 and set(native) == set(layout["lgpl_replaceable_native"]),
                "invalid replacement native scope")
        for name, row in native.items():
            require(row["original_sha256"] == prior[name] and row["sha256"] == paths[name],
                    "replacement native witness differs from independently pinned control")
        allowed = set(native) | set(layout["lgpl_replaceable_python"])
        require(set(paths) == set(prior) and {name for name in paths if paths[name] != prior[name]} == allowed,
                "replacement copy has unauthorized byte changes")
        replacement = {name: paths[name] for name in allowed}
    else:
        raise ContractError("unapproved diagnostic variant")
    require_payload(draft, paths, payload_hashes(bundle), replacement)
    require(paths["LightFringe.exe"] == closed["exe_sha256"], "EXE hash differs from locked payload")
    require_embedded_set(draft, closed["embedded_modules"])
    code = closed["embedded_code_sha256"]
    require(set(code) == set(closed["embedded_modules"]) and
            all(re.fullmatch(r"[0-9a-f]{64}", value) for value in code.values()), "missing code identity")
    require(set(closed["native_sha256"]) == native_paths(paths) and
            all(paths[name] == value for name, value in closed["native_sha256"].items()),
            "unbound native payload")
    release_packages = [
        {"module": name, "relative": path, "sha256": paths[path]}
        for name in ("PySide6", "shiboken6") for path in [f"Runtime/{name}/__init__.py"]
    ]
    require(release_packages == closed["release_python_modules"], "external package identity does not bind the payload")
