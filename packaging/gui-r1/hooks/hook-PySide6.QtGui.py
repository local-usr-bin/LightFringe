import json
from pathlib import Path,PurePosixPath
from PyInstaller.utils.hooks.qt import add_qt6_dependencies
CONFIG_DIR=Path(__file__).resolve().parent.parent
REPO_ROOT=CONFIG_DIR.parents[1]
R=json.loads((CONFIG_DIR/"build-roots.local.json").read_text(encoding="utf-8"))
for key in ("source","scripts","hooks","audit","build_env"):
    value=R[key]
    if not isinstance(value,str) or not value:
        raise ValueError("Configure explicit local path: "+key)
    path=Path(value)
    R[key]=str((path if path.is_absolute() else REPO_ROOT/path).resolve())
hiddenimports,collected,datas=add_qt6_dependencies(__file__)
allowed={("platforms","qwindows.dll"),("imageformats","qgif.dll"),("imageformats","qico.dll"),("imageformats","qjpeg.dll")}
binaries=[];removed=[]
for source,destination in collected:
    parts=PurePosixPath(str(destination).replace("\\","/")).parts
    if "plugins" not in [p.casefold() for p in parts]:raise RuntimeError("Unexpected non-plugin QtGui binary")
    name=PurePosixPath(str(source).replace("\\","/")).name.casefold()
    if (parts[-1].casefold(),name) in allowed:binaries.append((source,destination))
    else:removed.append({"source":source,"destination":destination})
with (Path(R["audit"])/"RELEASE-QT-GUI-HOOK-FILTER.json").open("x",encoding="utf-8") as f:
    json.dump({"policy":"Pre-dependency-recursion QtGui plugin roots, original helper imports/data retained","allowed":[list(x) for x in sorted(allowed)],"kept":binaries,"removed":removed},f,indent=2)
