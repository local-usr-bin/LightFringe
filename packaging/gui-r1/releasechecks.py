"""Bounded, explicit release checks; never used by the default product entry.

Contract additions: release_version, release_build, release_python_modules,
replacement_markers and replacement_native. No installation, subprocess launch,
product source write, library mutation or persistent environment change occurs
here. The parent creates and identities any disposable replacement copy first.
"""
import importlib
import importlib.machinery
import json
import sys
import time
import traceback
from pathlib import Path

import lfdiagnostics as D
import release_contract as R


def _failure(exc):
    return {"type": type(exc).__name__, "message": str(exc),
            "traceback": "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))}


def _record_cleanup(name, operation):
    try:
        return operation()
    except BaseException as exc:
        D.RESULT.setdefault("cleanup_failures", []).append({"action": name, **_failure(exc)})
        traceback.print_exception(type(exc), exc, exc.__traceback__, file=sys.stderr)
        return None


def _dispose_application(stage):
    """Release an ended QApplication; never terminate a process or worker."""
    from PySide6.QtCore import QCoreApplication, QEvent
    from PySide6.QtWidgets import QApplication
    import shiboken6
    app = QApplication.instance()
    row = {"stage": stage, "present": app is not None, "disposed": False}
    D.RESULT.setdefault("application_disposals", []).append(row)
    if app is None:
        row["disposed"] = True
        return
    windows = list(app.topLevelWidgets())
    row["visible_windows_before"] = [w.windowTitle() for w in windows if w.isVisible()]
    for window in windows:
        if hasattr(window, "airy_view"):
            window.close()
            D.closed_workers(window)
    D.require(not any(w.isVisible() for w in app.topLevelWidgets()),
              "application cleanup found a remaining visible window")
    app.quit()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    app.processEvents()
    shiboken6.delete(app)
    row["disposed"] = QApplication.instance() is None
    D.require(row["disposed"], "QApplication singleton survived explicit disposal")


def _external_python_identity(mode):
    expected = D.C["release_python_modules"]
    D.require(isinstance(expected, list) and len(expected) == 2,
              "exactly two external Python package identities are required")
    D.require({r["module"] for r in expected} == {"PySide6", "shiboken6"},
              "unexpected external Python package identity set")
    rows = []
    D.RESULT["external_python_packages"] = rows
    for item in expected:
        name = item["module"]
        module = importlib.import_module(name)
        origin = Path(module.__file__).resolve()
        relative = Path(item["relative"])
        D.require(not relative.is_absolute() and ".." not in relative.parts,
                  "external package path must be a confined relative path")
        target = (D.RUNTIME / relative).resolve()
        spec = module.__spec__
        row = {"module": name, "path": str(origin),
               "spec_origin": None if spec is None else spec.origin,
               "loader": type(module.__loader__).__module__ + "." + type(module.__loader__).__qualname__,
               "sha256": D.sha(origin), "version": getattr(module, "__version__", None)}
        rows.append(row)
        D.require(D.within(origin, D.RUNTIME) and D.canon(origin) == D.canon(target),
                  "external package loaded from an unexpected path: " + name)
        D.require(spec is not None and D.canon(spec.origin) == D.canon(target),
                  "external package spec origin mismatch: " + name)
        D.require(isinstance(module.__loader__, importlib.machinery.SourceFileLoader),
                  "package did not execute through an external source loader: " + name)
        D.require(row["sha256"].lower() == item["sha256"].lower(),
                  "external package byte identity mismatch: " + name)
        D.require(row["version"] == "6.8.3", "binding package version changed: " + name)
    markers = D.C["replacement_markers"]
    D.require(isinstance(markers, list), "replacement markers must be a list")
    marker_rows = []
    D.RESULT["replacement_source_markers"] = marker_rows
    if mode == "control":
        D.require(markers == [], "control cannot authorize replacement source markers")
    else:
        D.require(len(markers) == 2 and {r["module"] for r in markers} == {"PySide6", "shiboken6"},
                  "replacement requires two exact package markers")
        for item in markers:
            D.require(isinstance(item["attribute"], str) and item["attribute"].startswith("__lf_"),
                      "unexpected replacement marker attribute")
            D.require(isinstance(item["value"], str) and bool(item["value"]),
                      "replacement marker must contain a nonempty exact value")
            actual = getattr(sys.modules[item["module"]], item["attribute"], None)
            marker_rows.append({**item, "actual": actual, "matched": actual == item["value"]})
            D.require(actual == item["value"], "replacement Python source marker did not execute")
    import lightfringe
    version = lightfringe.__version__
    build = lightfringe.__build__
    D.RESULT["release_metadata"] = {"version": version, "build": build,
                                    "baseline": lightfringe.__baseline__}
    R.require_product(D.DRAFT, version, build, lightfringe.__baseline__)
    D.verify_product_modules()


def _control_gui_pdf():
    """Observe the actual window used by the five-mode diagnostic writer."""
    from lightfringe import airy_pdf_gui
    original = airy_pdf_gui.AiryPdfMainWindow
    observations = []
    D.RESULT["control_window_observations"] = observations

    def observed_window():
        window = original()
        row = {"class": type(window).__module__ + "." + type(window).__qualname__,
               "title": window.windowTitle(), "initial_mode": window.mode.currentIndex(),
               "observation_wiring": "test-only constructor factory returns the original actual window class"}
        observations.append(row)
        try:
            from PySide6.QtWidgets import QApplication
            app_version = QApplication.instance().applicationVersion()
            R.require_window(D.DRAFT, app_version, row["title"])
            row["application_version"] = app_version
        except BaseException:
            _record_cleanup("control window after metadata failure", window.close)
            raise
        return window

    airy_pdf_gui.AiryPdfMainWindow = observed_window
    try:
        D.gui_pdf()
    finally:
        airy_pdf_gui.AiryPdfMainWindow = original
    D.require(len(observations) == 1, "GUI helper did not create exactly one actual window")
    D.require(D.RESULT["gui_pdf"]["status"] == "PASS" and
              [row["mode"] for row in D.RESULT["gui_pdf"]["modes"]] == [row["id"] for row in D.DRAFT["modes"]],
              "five-mode PDF writer did not complete all modes")
    D.require(D.RESULT["gui_close"]["closed"] and not D.RESULT["gui_close"]["worker_running"],
              "five-mode PDF writer did not close naturally")


def _replacement_native_witness():
    from PySide6.QtCore import QObject, qVersion
    import shiboken6
    D.modules("replacement-native-witness", True)
    snapshot = D.RESULT["module_snapshots"][-1]
    identities = D.C["replacement_native"]
    D.require(isinstance(identities, list) and len(identities) == 3,
              "replacement native witness must bind exactly three files")
    D.require({Path(r["relative"]).name.lower() for r in identities} ==
              {"qt6core.dll", "pyside6.abi3.dll", "shiboken6.abi3.dll"},
              "replacement native witness set changed")
    rows = []
    D.RESULT["replacement_native_witness"] = rows
    for item in identities:
        relative = Path(item["relative"])
        D.require(not relative.is_absolute() and ".." not in relative.parts,
                  "native witness path must be confined relative path")
        target = (D.RUNTIME / relative).resolve()
        matches = [r for r in snapshot["modules"] if D.canon(r["path"]) == D.canon(target)]
        D.require(len(matches) == 1, "replacement DLL actual loading is not uniquely observed")
        row = {**item, "actual": matches[0],
               "evidence_scope": "actual loaded-module path plus contemporaneous disk hash; not a loaded-memory image hash"}
        rows.append(row)
        D.require(item["sha256"].lower() != item["original_sha256"].lower(),
                  "replacement witness is byte-identical to original")
        D.require(matches[0]["sha256"].lower() == item["sha256"].lower(),
                  "modified DLL actual file identity was not observed")
    obj = QObject()
    try:
        obj.setObjectName("LightFringe compatible replacement witness")
        actual = {"qVersion": qVersion(), "object_name": obj.objectName(),
                  "shiboken_isValid": bool(shiboken6.isValid(obj))}
        D.RESULT["replacement_native_api"] = actual
        D.require(actual["qVersion"] == "6.8.3" and actual["shiboken_isValid"] and
                  actual["object_name"] == "LightFringe compatible replacement witness",
                  "modified native libraries did not preserve bounded QObject API behavior")
    finally:
        shiboken6.delete(obj)
    D.require(not shiboken6.isValid(obj), "replacement probe QObject was not disposed")
    D.RESULT["replacement_native_api"]["object_disposed"] = True


def _actual_main_probe():
    """Run the unchanged real main with a bounded, app-owned observation timer."""
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication
    from lightfringe import __main__ as entry
    from lightfringe.airy_pdf_gui import AiryPdfMainWindow
    D.require(QApplication.instance() is None, "actual main probe requires no existing QApplication")
    original_application = entry.QApplication
    original_argv = sys.argv[:]
    row = {"status": "STARTED", "ticks": [], "main_return": None,
           "window_observed": False, "close_requested": False,
           "observation_wiring": "test-only QApplication factory returns original real QApplication and installs an app-owned QTimer; product main and window class unchanged",
           "timer_interval_ms": 25, "maximum_ticks": 120, "deadline_seconds": 5.0}
    D.RESULT["actual_main_probe"] = row
    holder = {"app": None, "timer": None, "window": None, "callback_error": None}
    start = time.monotonic()

    def finish(error=None):
        if error is not None and holder["callback_error"] is None:
            holder["callback_error"] = _failure(error)
        if holder["timer"] is not None:
            holder["timer"].stop()
        window = holder["window"]
        try:
            if window is not None:
                row["close_requested"] = True
                row["close_return"] = bool(window.close())
                workers = D.closed_workers(window)
                row["circular_closed"] = workers["closed"]
                row["circular_worker_running"] = workers["worker_running"]
                row["closed_workers"] = workers
        except BaseException as exc:
            if holder["callback_error"] is None:
                holder["callback_error"] = _failure(exc)
            else:
                D.RESULT.setdefault("cleanup_failures", []).append({"action": "actual main window close", **_failure(exc)})
        finally:
            if holder["app"] is not None:
                holder["app"].quit()

    def tick():
        try:
            elapsed = time.monotonic() - start
            app = holder["app"]
            windows = [w for w in app.topLevelWidgets() if isinstance(w, AiryPdfMainWindow)]
            row["ticks"].append({"number": len(row["ticks"]) + 1, "elapsed_seconds": elapsed,
                                  "actual_window_count": len(windows),
                                  "visible_count": sum(bool(w.isVisible()) for w in windows)})
            D.require(len(windows) <= 1, "actual main created multiple product windows")
            if windows:
                holder["window"] = windows[0]
            if windows and windows[0].isVisible():
                window = windows[0]
                row.update({"window_observed": True, "title": window.windowTitle(),
                            "window_class": type(window).__module__ + "." + type(window).__qualname__,
                            "mode_index": window.mode.currentIndex(),
                            "application_name": app.applicationName()})
                R.require_window(D.DRAFT, app.applicationVersion(), row["title"])
                row["application_version"] = app.applicationVersion()
                row["icon_present"] = not app.windowIcon().isNull() and not window.windowIcon().isNull()
                D.require(row["icon_present"], "actual main did not install the packaged application icon")
                D.require(row["mode_index"] == 0, "actual main did not select single slit")
                D.modules("actual-main-visible", True)
                finish()
            elif elapsed >= 5.0 or len(row["ticks"]) >= 120:
                finish(RuntimeError("actual product main observation reached its bounded deadline"))
        except BaseException as exc:
            finish(exc)

    def observed_application(argv):
        D.require(holder["app"] is None, "actual main created a second QApplication")
        app = original_application(argv)
        holder["app"] = app
        timer = QTimer(app)
        timer.setInterval(25)
        timer.timeout.connect(tick)
        holder["timer"] = timer
        timer.start()
        return app

    entry.QApplication = observed_application
    sys.argv = [original_argv[0]]
    try:
        row["main_return"] = entry.main()
    finally:
        entry.QApplication = original_application
        sys.argv = original_argv
        if holder["timer"] is not None:
            holder["timer"].stop()
        if holder["window"] is not None and not row.get("close_requested"):
            finish()
    row["elapsed_seconds"] = time.monotonic() - start
    row["callback_error"] = holder["callback_error"]
    D.require(holder["callback_error"] is None, "actual main callback failed: " + str(holder["callback_error"]))
    D.require(row["window_observed"] and row["main_return"] == 0 and row["close_requested"] and
              row.get("close_return") and row.get("circular_closed") and
              row.get("circular_worker_running") is False,
              "actual main did not show and close its actual window normally")
    row["status"] = "PASS"


def main():
    original_argv = sys.argv[:]
    mode = None
    audit = None
    label = "release-invalid"
    fallback = {"status": "FAIL", "events": [], "module_snapshots": [],
                "full_science35": "NOT_RUN", "historical_native_gate": "CLOSED"}
    try:
        D.require(len(original_argv) == 7 and original_argv[1] == "--lf-release-check",
                  "invalid explicit release-check invocation")
        mode = original_argv[2]
        D.require(mode in ("control", "replacement"), "unsupported release-check mode")
        label = "release-" + mode
        sys.argv = [original_argv[0], "--lf-diagnostic", "gui-pdf", *original_argv[3:]]
        D._initialize(variant=mode)
        audit = D.AUDIT
        D.LABEL = label
        D.RESULT.update({"label": label, "release_check": mode, "full_science35": "NOT_RUN",
                         "historical_native_gate": "CLOSED", "cleanup_failures": []})
        D.early_probe()
        sys.argv = original_argv
        _external_python_identity(mode)
        import numpy as np
        import scipy
        D.compatibility(np, scipy)
        D.require(len(D.RESULT["compatibility"]) == 9 and
                  all(r["status"] == "PASS" for r in D.RESULT["compatibility"]),
                  "original nine bounded compatibility checks did not all complete")
        if mode == "control":
            D.RESULT["multiaperture_science"] = D.multiaperture_checks()
            D.require(D.C["replacement_native"] == [], "control cannot authorize modified native files")
            _control_gui_pdf()
        else:
            _replacement_native_witness()
            _actual_main_probe()
        D.RESULT["environment_end"] = D.environment()
        D.RESULT["status"] = ("PASS_WITH_ENVIRONMENT_CAVEAT" if
                               D.RESULT.get("external_environment_assessment", {}).get("observed") else "PASS")
        D.emit("COMPLETE_RELEASE_CHECK", mode=mode, status=D.RESULT["status"])
    except BaseException as exc:
        if D.RESULT is None:
            D.RESULT = fallback
        D.RESULT["status"] = "FAIL"
        D.RESULT["error"] = _failure(exc)
        traceback.print_exception(type(exc), exc, exc.__traceback__, file=sys.stderr)
    finally:
        sys.argv = original_argv
        if D.RESULT is None:
            D.RESULT = fallback
        if "PySide6.QtWidgets" in sys.modules:
            _record_cleanup("final QApplication disposal", lambda: _dispose_application(label))
        if D.C is not None and D.RESULT.get("environment_begin") is not None:
            _record_cleanup("final persistent environment readback",
                            lambda: D.RESULT.update({"environment_final": D.environment()}))
        if D.RESULT.get("cleanup_failures"):
            D.RESULT["status"] = "FAIL"
        D.RESULT["receipt_valid"] = False
        if audit is not None:
            try:
                D.RESULT["receipt_valid"] = True
                with (audit / (label + "-result.json")).open("x", encoding="utf-8", newline="\n") as stream:
                    json.dump(D.RESULT, stream, ensure_ascii=False, indent=2)
            except BaseException as exc:
                D.RESULT["receipt_valid"] = False
                D.RESULT["status"] = "FAIL"
                print("RELEASE_RECEIPT_FAILURE " + json.dumps(_failure(exc), ensure_ascii=True), file=sys.stderr, flush=True)
        else:
            D.RESULT["status"] = "FAIL"
            print("RELEASE_RECEIPT_UNAVAILABLE: no validated audit directory", file=sys.stderr, flush=True)
    return 0 if D.RESULT.get("status") in ("PASS", "PASS_WITH_ENVIRONMENT_CAVEAT") and D.RESULT.get("receipt_valid") else 1
