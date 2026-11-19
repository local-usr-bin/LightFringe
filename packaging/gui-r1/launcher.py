import sys
if __name__=="__main__":
    if len(sys.argv)>1 and sys.argv[1]=="--lf-release-check":
        from releasechecks import main
    elif len(sys.argv)>1 and sys.argv[1]=="--lf-diagnostic":
        from lfdiagnostics import main
    else:
        from lightfringe.__main__ import main
    raise SystemExit(main())