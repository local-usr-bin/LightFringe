import sys
if len(sys.argv)>1 and sys.argv[1]=="--lf-diagnostic":
    from lfdiagnostics import early_probe
    early_probe()
