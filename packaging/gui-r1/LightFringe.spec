import json,re,hashlib
from pathlib import Path
from PyInstaller.utils.hooks import collect_data_files
SPEC_DIR=Path(SPECPATH).resolve()
REPO_ROOT=SPEC_DIR.parents[1]
R=json.loads((SPEC_DIR/"build-roots.local.json").read_text(encoding="utf-8"))
for key in ("source","scripts","hooks","audit","build_env"):
    value=R[key]
    if not isinstance(value,str) or not value:
        raise ValueError("Configure explicit local path: "+key)
    path=Path(value)
    R[key]=str((path if path.is_absolute() else REPO_ROOT/path).resolve())
SRC=Path(R["source"]);SCRIPTS=Path(R["scripts"]);AUDIT=Path(R["audit"])
removed=[]
def excluded(entry):
    names=[Path(str(entry[i]).replace("\\","/")).name.lower() for i in (0,1) if len(entry)>i and entry[i]]
    for name in names:
        if re.match(r"^(msvcp|msvcr|vcruntime|concrt|vcomp|vcamp|vccorlib|mfc|mfcm|atl)\d.*\.dll$",name) or name=="ucrtbase.dll" or re.match(r"^(api-ms-win-|ext-ms-win-).*\.dll$",name):return True
    return False
def clean(toc,stage):
    kept=[]
    for e in toc:
        if excluded(e):removed.append({"stage":stage,"entry":list(e)})
        else:kept.append(e)
    return kept
BUILD_ENV=Path(R["build_env"])
qt_keep={"QtCore","QtGui","QtWidgets"}
qt_excludes=["PySide6."+p.stem for p in (BUILD_ENV/"Lib"/"site-packages"/"PySide6").glob("Qt*.pyd") if p.stem not in qt_keep]
ICON=SRC/"lightfringe"/"assets"/"LightFringe.ico"
datas=collect_data_files("tzdata")
datas += [(str(ICON),"lightfringe/assets")]
datas += [(str(SRC/"references"/name),"science-data") for name in ("numerical-reference.json","independent-science.json")]
datas += [(str(SRC/"lightfringe"/name),"science-source") for name in ("circular_model.py","circular_sampling.py","circular_report.py")]
a=Analysis([str(SCRIPTS/"launcher.py")],pathex=[str(SRC),str(SCRIPTS)],binaries=[(str(BUILD_ENV/name),".") for name in ("libssl-3-x64.dll","libcrypto-3-x64.dll")],datas=datas,
    hiddenimports=["releasechecks","lfdiagnostics","lightfringe.__main__","scipy.linalg","scipy.special","numpy.fft._pocketfft_umath","numpy._core._multiarray_umath"],
    hookspath=[R["hooks"]],runtime_hooks=[str(SCRIPTS/"early-origin-hook.py")],
    excludes=["PyQt5","PyQt6","PySide2","matplotlib","IPython","pytest","tkinter"]+qt_excludes,noarchive=False,module_collection_mode={"PySide6":"py","shiboken6":"py"})
diag_sources=[x[1] for x in a.pure if x[0]=="lfdiagnostics"]
assert len(diag_sources)==1 and Path(diag_sources[0]).resolve()==(SCRIPTS/"lfdiagnostics.py").resolve(),diag_sources
mesa_entries=[e for e in a.binaries if str(e[0]).replace("\\","/").casefold()=="pyside6/opengl32sw.dll"]
assert len(mesa_entries)==1,mesa_entries
assert Path(mesa_entries[0][1]).resolve().is_relative_to(BUILD_ENV.resolve())
assert hashlib.sha256(Path(mesa_entries[0][1]).read_bytes()).hexdigest()=="0fe371cb37260efa36442c1b940aa7f8a98528380d4dc2523c7c3c020c57cc47"
a.binaries=[e for e in a.binaries if e not in mesa_entries]
with (AUDIT/"MESA-EXCLUSION.json").open("x",encoding="utf-8") as f:json.dump({"scope":"One optional software-OpenGL fallback only; product uses QWidget/QPainter/QPdfWriter","entries":[list(x) for x in mesa_entries],"count":len(mesa_entries)},f,indent=2)
a.binaries=clean(a.binaries,"Analysis.binaries")
qt_dlls={Path(str(e[0]).replace("\\","/")).name.lower() for e in a.binaries if Path(str(e[0]).replace("\\","/")).name.lower().startswith("qt6") and str(e[0]).lower().endswith(".dll")}
assert qt_dlls=={"qt6core.dll","qt6gui.dll","qt6widgets.dll"},qt_dlls
for entry in a.binaries:
    source=Path(entry[1]).resolve()
    assert source.is_relative_to(BUILD_ENV.resolve()),"Uncontrolled binary source: "+str(entry)
for name in ("libssl-3-x64.dll","libcrypto-3-x64.dll"):
    found=[e for e in a.binaries if Path(str(e[0]).replace("\\","/")).name.lower()==name]
    assert len(found)==1 and Path(found[0][1]).resolve()==(BUILD_ENV/name).resolve(),found
allowed_plugins={("platforms","qwindows.dll"),("imageformats","qgif.dll"),("imageformats","qico.dll"),("imageformats","qjpeg.dll"),("styles","qmodernwindowsstyle.dll")}
for e in a.binaries:
    parts=Path(str(e[0]).replace("\\","/")).parts
    if "plugins" in [p.lower() for p in parts]:
        assert (parts[-2].lower(),parts[-1].lower()) in allowed_plugins,e
a.datas=clean(a.datas,"Analysis.datas")
pyz=PYZ(a.pure)
exe=EXE(pyz,a.scripts,[],exclude_binaries=True,name="LightFringe",debug=False,bootloader_ignore_signals=False,strip=False,upx=False,console=False,contents_directory="Runtime",disable_windowed_traceback=False,version=str(SCRIPTS/"version-resource.txt"),icon=str(ICON))
exe.dependencies=clean(exe.dependencies,"EXE.dependencies")
assert not any(excluded(x) for x in [*a.binaries,*a.datas,*exe.dependencies])
coll=COLLECT(exe,a.binaries,a.datas,strip=False,upx=False,name="LightFringe")
with (AUDIT/"RELEASE-VC-TOC-EXCLUSIONS.json").open("x",encoding="utf-8") as f:json.dump({"policy":"Exclude uncontrolled build-environment VC at all TOC boundaries; attach five sealed official 14.52 files to Runtime afterwards","entries":removed,"count":len(removed)},f,indent=2)
with (AUDIT/"RELEASE-COLLECTED-TOC.json").open("x",encoding="utf-8") as f:json.dump({"binaries":[list(x) for x in a.binaries],"datas":[list(x) for x in a.datas],"exe_dependencies":[list(x) for x in exe.dependencies]},f,indent=2)
