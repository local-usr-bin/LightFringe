import ctypes,datetime,hashlib,json,math,os,re,struct,sys,time,traceback,winreg
from ctypes import wintypes as W
from pathlib import Path
C=MODE=LABEL=AUDIT=RUNTIME=RESULT=None
def digest(data):return hashlib.sha256(data).hexdigest()

def sha(path):return digest(Path(path).read_bytes())

def canon(path):return os.path.normcase(str(Path(path).resolve()))

def within(path,root):
    try:Path(path).resolve().relative_to(Path(root).resolve());return True
    except ValueError:return False

def emit(stage,**kw):
    event={"utc":datetime.datetime.now(datetime.timezone.utc).isoformat(),"monotonic_ns":time.perf_counter_ns(),"pid":os.getpid(),"stage":stage,**kw}
    RESULT["events"].append(event)
    if sys.stdout is not None:
        print(json.dumps(event,ensure_ascii=True),flush=True)

def save_new(name,value):
    with (AUDIT/name).open("x",encoding="utf-8",newline="\n") as f:json.dump(value,f,ensure_ascii=False,indent=2)

def require(test,message):
    if not bool(test):raise RuntimeError(message)

def environment():
    rows=[]
    for scope,hive,key in [("User",winreg.HKEY_CURRENT_USER,"Environment"),("Machine",winreg.HKEY_LOCAL_MACHINE,r"SYSTEM\CurrentControlSet\Control\Session Manager\Environment")]:
        with winreg.OpenKey(hive,key,0,winreg.KEY_READ|winreg.KEY_WOW64_64KEY) as k:raw,kind=winreg.QueryValueEx(k,"Path")
        expanded=winreg.ExpandEnvironmentStrings(raw) if kind==winreg.REG_EXPAND_SZ else raw
        expected=next(r for r in C["persistent_paths"] if r["Scope"]==scope)
        require(raw==expected["Raw"] and expanded==expected["Expanded"],"persistent "+scope+" PATH drift")
        rows.append({"scope":scope,"raw":raw,"expanded":expanded,"raw_sha256":digest(raw.encode("utf-8")),"expanded_sha256":digest(expanded.encode("utf-8"))})
    return {"persistent":rows,"process_path":os.environ.get("PATH",""),"process_path_sha256":digest(os.environ.get("PATH","").encode("utf-8")),"OPENBLAS_NUM_THREADS":os.environ.get("OPENBLAS_NUM_THREADS"),"OMP_NUM_THREADS":os.environ.get("OMP_NUM_THREADS")}

def file_version(path):
    ignored=W.DWORD();size=V.GetFileVersionInfoSizeW(str(path),ctypes.byref(ignored))
    if not size:return None
    buffer=ctypes.create_string_buffer(size)
    require(V.GetFileVersionInfoW(str(path),0,size,buffer),"GetFileVersionInfoW failed")
    ptr=ctypes.c_void_p();length=W.UINT()
    require(V.VerQueryValueW(buffer,"\\",ctypes.byref(ptr),ctypes.byref(length)) and length.value>=52,"VerQueryValueW failed")
    words=struct.unpack("<13I",ctypes.string_at(ptr,52));require(words[0]==0xFEEF04BD,"bad version signature")
    return ".".join(map(str,[words[2]>>16,words[2]&65535,words[3]>>16,words[3]&65535]))

def module_file_company(path):
    ignored=W.DWORD();size=V.GetFileVersionInfoSizeW(str(path),ctypes.byref(ignored))
    if not size:return None
    buffer=ctypes.create_string_buffer(size)
    if not V.GetFileVersionInfoW(str(path),0,size,buffer):return None
    ptr=ctypes.c_void_p();length=W.UINT()
    if not V.VerQueryValueW(buffer,r"\VarFileInfo\Translation",ctypes.byref(ptr),ctypes.byref(length)) or length.value<4:return None
    lang,codepage=struct.unpack("<HH",ctypes.string_at(ptr,4))
    key=rf"\StringFileInfo\{lang:04x}{codepage:04x}\CompanyName"
    ptr=ctypes.c_void_p();length=W.UINT()
    if not V.VerQueryValueW(buffer,key,ctypes.byref(ptr),ctypes.byref(length)) or not ptr.value:return None
    return ctypes.wstring_at(ptr.value).strip()

def modules(stage,need_science=False):
    capacity=256;calls=[];issues=[];environment_issues=[];rows=[];vc=[];blas=[];external=[]
    for attempt in range(4):
        handles=(W.HMODULE*capacity)();needed=W.DWORD()
        ok=P.EnumProcessModulesEx(HANDLE,handles,ctypes.sizeof(handles),ctypes.byref(needed),3)
        calls.append({"api":"EnumProcessModulesEx","return":int(ok),"last_error":None if ok else ctypes.get_last_error(),"needed_bytes":needed.value,"buffer_bytes":ctypes.sizeof(handles)})
        require(ok,"EnumProcessModulesEx failed")
        if needed.value<=ctypes.sizeof(handles):break
        capacity=needed.value//ctypes.sizeof(W.HMODULE)+32
    else:raise RuntimeError("module list did not stabilize within bounded capture")
    count=needed.value//ctypes.sizeof(W.HMODULE)
    approved_by_name={}
    for item in C["bundle_native"]:
        approved_by_name.setdefault(Path(item["relative"]).name.lower(),[]).append(item)
    host_catalog={canon(x["Path"]):x for x in C["host_component_identities"]}
    for h in handles[:count]:
        buf=ctypes.create_unicode_buffer(32768);n=P.GetModuleFileNameExW(HANDLE,h,buf,len(buf))
        calls.append({"api":"GetModuleFileNameExW","module_handle":h,"return":int(n),"last_error":None if n else ctypes.get_last_error()})
        if not 0<n<len(buf)-1:
            issues.append({"kind":"MODULE_PATH_QUERY_FAILED","handle":h});continue
        path=Path(buf.value);name=path.name.lower()
        row={"path":str(path),"basename":name,"module_handle":h}
        try:
            row["sha256"]=sha(path);row["version"]=file_version(path)
            if re.match(r"^(msvcp|vcruntime|msvcr|concrt|vcomp|vcamp|vccorlib)\d.*\.dll$",name):
                expected=next((x for x in C["system_vc"] if Path(x["Path"]).name.lower()==name),None)
                row["category"]="REQUIRED_CENTRAL_VC"
                if expected is None or canon(path)!=canon(expected["Path"]) or row["sha256"]!=expected["SHA256"]:
                    issues.append({"kind":"VC_ORIGIN_OR_IDENTITY_VIOLATION","path":str(path)})
                vc.append(row)
            elif name in approved_by_name:
                expected=next((x for x in approved_by_name[name] if canon(path)==canon(RUNTIME/x["relative"])),None)
                row["category"]="REQUIRED_PRODUCT_DEPENDENCY"
                if expected is None or row["sha256"]!=expected["sha256"]:
                    issues.append({"kind":"PRODUCT_DEPENDENCY_ORIGIN_OR_IDENTITY_VIOLATION","path":str(path)})
            elif within(path,RUNTIME):
                row["category"]="UNAPPROVED_BUNDLE_NATIVE"
                issues.append({"kind":"UNAPPROVED_BUNDLE_NATIVE","path":str(path)})
            elif canon(path) in host_catalog:
                expected=host_catalog[canon(path)]
                if expected["SHA256"]==row["sha256"] and expected["Signature"]=="Valid":
                    row.update({"category":expected["Category"],"company":expected["Company"],"prelaunch_file_version":expected["Version"],"signature":expected["Signature"],"signer":expected["Signer"],"identity_assessment":"Exact path/hash and prelaunch valid signature catalog; current file identity, not loaded-memory hash","product_dependency":False,"bundled":False})
                    if expected["Category"]=="WINDOWS_SYSTEM_COMPONENT":
                        if not within(path,C["windows_directory"]):environment_issues.append({"kind":"SYSTEM_IDENTITY_OUTSIDE_WINDOWS","path":str(path)})
                    else:external.append(row)
                else:
                    row["category"]="HOST_COMPONENT_IDENTITY_CHANGED"
                    environment_issues.append({"kind":"HOST_COMPONENT_IDENTITY_CHANGED","path":str(path)})
            elif within(path,C["windows_directory"]):
                row["company"]=module_file_company(path)
                if row["company"] and "microsoft" in row["company"].lower():
                    row["category"]="WINDOWS_SYSTEM_COMPONENT"
                else:
                    row["category"]="WINDOWS_LOCATION_IDENTITY_UNRESOLVED"
                    environment_issues.append({"kind":"WINDOWS_LOCATION_ALONE_INSUFFICIENT","path":str(path),"company":row["company"]})
            else:
                expected=host_catalog.get(canon(path))
                if expected and expected["SHA256"]==row["sha256"] and expected["Signature"]=="Valid":
                    row.update({"category":"USER_ENVIRONMENT_IME","identity_assessment":"MATCHES_PRELAUNCH_VENDOR_SIGNATURE_HASH_AND_VERSION_CATALOG","company":expected["Company"],"signature":expected["Signature"],"signer":expected["Signer"],"product_dependency":False,"bundled":False,"assessment":"Observed user input component; permitted as environment caveat, not a package dependency or a native-risk resolution"})
                else:
                    row.update({"category":"EXTERNAL_ENVIRONMENT_UNRESOLVED","product_dependency":False,"bundled":False,"assessment":"Identity/source requires review; not promoted to approved package input; functional test result and product dependency result remain separate"})
                external.append(row)
                if row["category"]=="EXTERNAL_ENVIRONMENT_UNRESOLVED":environment_issues.append({"kind":"EXTERNAL_IDENTITY_REQUIRES_ASSESSMENT","path":str(path)})
            if name.startswith("libscipy_openblas"):
                expected=next((x for x in C["openblas"] if Path(x["path"]).name.lower()==name),None)
                if expected is None or canon(path)!=canon(expected["path"]) or row["sha256"]!=expected["sha256"]:
                    issues.append({"kind":"OPENBLAS_ORIGIN_OR_IDENTITY_VIOLATION","path":str(path)})
                blas.append(row)
            if name==C["old_import"]:issues.append({"kind":"HASHED_MSVC_LOADED","path":str(path)})
        except Exception as exc:
            row["identity_error"]={"type":type(exc).__name__,"message":str(exc)}
            issues.append({"kind":"MODULE_IDENTITY_UNAVAILABLE","path":str(path),"error":str(exc)})
        rows.append(row)
    if not any(x["basename"]=="vcruntime140.dll" for x in vc):issues.append({"kind":"CENTRAL_VCRUNTIME140_NOT_OBSERVED"})
    if need_science:
        if not any(x["basename"]=="msvcp140.dll" for x in vc):issues.append({"kind":"CENTRAL_MSVCP140_NOT_OBSERVED"})
        if {x["basename"] for x in blas}!={Path(x["path"]).name.lower() for x in C["openblas"]}:issues.append({"kind":"OPENBLAS_SET_INCOMPLETE"})
    snap={"stage":stage,"utc":datetime.datetime.now(datetime.timezone.utc).isoformat(),"modules":rows,"win32_calls":calls,"vc":vc,"openblas":blas,"external_environment":external,"product_dependency_violations":issues,"host_environment_identity_issues":environment_issues,"scope":"Current-process snapshots, not a pre-main/unloaded-module event history; external environment components do not change mandatory product source rules"}
    RESULT["module_snapshots"].append(snap)
    save_new(LABEL+"-"+stage+"-modules.json",snap)
    RESULT["external_environment_assessment"]={"observed":any(s.get("external_environment") for s in RESULT["module_snapshots"]),"unresolved":any(r["category"]=="EXTERNAL_ENVIRONMENT_UNRESOLVED" for s in RESULT["module_snapshots"] for r in s.get("external_environment",[]))}
    emit("MODULES",capture=stage,count=len(rows),vc=[x["path"] for x in vc],blas=[x["path"] for x in blas],external=[{"path":x["path"],"category":x["category"]} for x in external],product_dependency_violations=issues)
    require(not issues,"mandatory product module identity/source check failed")
    require(not environment_issues,"host environment identity requires separate assessment; not classified as a package dependency failure")
def module_origin(module):
    path=Path(module.__file__).resolve()
    require(within(path,RUNTIME) or within(path,C["source"]),"Python module source outside isolated copy: "+str(path))
    return str(path)

def compatibility(np,scipy):
    from scipy import linalg,special
    require(np.__version__=="2.2.6" and scipy.__version__=="1.16.3","runtime package version mismatch")
    checks=[]
    def check(name,test,**kw):
        row={"name":name,"status":"PASS" if bool(test) else "FAIL",**kw};checks.append(row)
        require(test,"compatibility failed: "+name)
    a=np.arange(48,dtype=np.int64).reshape(6,8)[:,::2]
    check("noncontiguous_integer_ufunc_dtype",np.array_equal(a+a,2*a) and np.array_equal(a.astype(np.float64),a))
    check("empty_array",np.add(np.empty(0),1).size==0)
    values=np.array([np.nan,np.inf,-np.inf,0.])
    check("nan_inf_contract",np.array_equal(np.isnan(values),[True,False,False,False]) and np.isposinf(values[1]) and np.isneginf(values[2]))
    try:np.ones((2,3))+np.ones((5,))
    except ValueError:check("broadcast_exception",True)
    else:check("broadcast_exception",False)
    impulse=np.zeros(16);impulse[0]=1.
    spectrum=np.fft.fft(impulse)
    check("fft_impulse_exact",np.array_equal(spectrum,np.ones(16,dtype=complex)) and np.array_equal(np.fft.ifft(spectrum).real,impulse),comparison="exact")
    check("real_fft_impulse_exact",np.array_equal(np.fft.irfft(np.fft.rfft(impulse),n=16),impulse),comparison="exact")
    matrix=np.array([[3.,1.],[1.,2.]]);x=np.array([1.,-1.]);rhs=np.array([2.,-1.])
    check("blas_matrix_product_exact",np.array_equal(matrix@x,rhs),comparison="exact")
    for name,solver in [("numpy_lapack",np.linalg.solve),("scipy_lapack",linalg.solve)]:
        got=solver(matrix,rhs);error=float(np.max(np.abs(got-x)))
        check(name,error<=5e-14,error=error,absolute_bound=5e-14)
    RESULT["python_module_origins"]={m.__name__:module_origin(m) for m in [np,scipy,linalg,special,sys.modules["numpy._core._multiarray_umath"],sys.modules["numpy.fft._pocketfft_umath"]]}
    RESULT["compatibility"]=checks

def scientific_checks(np,scipy):
    from decimal import Decimal,localcontext
    from dataclasses import replace
    from scipy.special import j1
    from lightfringe import circular_model as m,circular_sampling as s
    for key,mod in [("lightfringe/circular_model.py",m),("lightfringe/circular_sampling.py",s)]:
        require(sha(Path(C["science_source"])/Path(key).name)==C["source_hashes"][key],"frozen science source changed")
        module_origin(mod)
    refpath=Path(C["references"][0]["Path"]);corepath=Path(C["references"][1]["Path"])
    require(sha(refpath)==C["references"][0]["SHA256"] and sha(corepath)==C["references"][1]["SHA256"],"science reference changed")
    ref=json.loads(refpath.read_text(encoding="utf-8"));old=json.loads(corepath.read_text(encoding="utf-8"))
    checks=[]
    def check(name,passed,**evidence):
        checks.append(dict(name=name,status='PASS' if bool(passed) else 'FAIL',**evidence))
        require(bool(passed),'science contract failed: '+name)
    def reject(name,call,exception):
        try:call()
        except exception as exc:check(name,True,exception=type(exc).__name__);return
        except Exception as exc:check(name,False,wrong_exception=repr(exc));return
        check(name,False,reason='invalid request accepted')
    numeric=[]; maximum={n:0. for n in ('j1','amplitude','intensity')}
    with localcontext() as ctx:
        ctx.prec=110
        for row in ref['rows']:
            u=row['u'];values={'j1':float(j1(u)),'amplitude':float(m.normalized_amplitude(u)),'intensity':float(m.normalized_intensity(u))}
            errors={n:abs(Decimal.from_float(value)-Decimal(row[n+'_reference'])) for n,value in values.items()}
            good=all(error<=Decimal('5e-14') for error in errors.values())
            for n,error in errors.items():maximum[n]=max(maximum[n],float(error))
            numeric.append(dict(u=u,actual=values,reference={n:row[n+'_reference'] for n in values},absolute_error={n:str(v) for n,v in errors.items()},absolute_tolerance='5e-14',status='PASS' if good else 'FAIL'))
            require(good,'scientific reference exceeded at u='+str(u))
    check('historical_1473_J1_amplitude_intensity',len(numeric)==1473 and all(x['status']=='PASS' for x in numeric),rows=len(numeric),maximum_absolute_errors=maximum,tolerance=5e-14,reference_method=ref['reference'])
    integral=[]
    for row in old['numerical_comparisons']:
        u=row['input_u'];a=float(m.normalized_amplitude(u));i=float(m.normalized_intensity(u));j=float(j1(u))
        errors=[abs(a-float(row['reference_amplitude'])),abs(i-float(row['reference_intensity'])),abs(j-float(row['reference_J1']))]
        passed=max(errors)<=row['absolute_tolerance']
        integral.append(dict(u=u,errors=errors,tolerance=row['absolute_tolerance'],status='PASS' if passed else 'FAIL'))
    check('independent_disk_integral_reference21',len(integral)==21 and all(x['status']=='PASS' for x in integral),rows=len(integral))
    physical=[]
    for row in old['physical_comparisons']:
        p=m.CircularParameters.from_display_units(row['wavelength_nm'],row['diameter_um'],row['distance_m'])
        actual=float(m.intensity(p,row['x_m'],row['y_m']));radius=m.first_dark_radius(p)
        error=abs(actual-float(row['reference_intensity']));radius_error=abs(radius-float(row['reference_first_dark_radius_m']))
        passed=error<=row['intensity_tolerance'] and radius_error<=row['radius_tolerance_m']
        physical.append(dict(inputs=row,actual_intensity=actual,actual_first_dark_radius_m=radius,intensity_error=error,radius_error=radius_error,status='PASS' if passed else 'FAIL'))
    check('physical_points_and_Airy_radius8',len(physical)==8 and all(x['status']=='PASS' for x in physical),rows=len(physical))
    crit=(550/1e9)*2*383/(24*.04)
    pa=m.CircularParameters(550/1e9,crit*(1-1e-10),2.)
    areas=[]
    for row in old['pixel_area_comparisons']:
        actual=float(s.pixel_area_mean(pa,row['x_m'],row['y_m'],row['pitch_m']))
        error=abs(actual-row['reference_16x16_disk_integral'])
        passed=error<row['tolerance']
        areas.append(dict(inputs=row,actual=actual,absolute_error=error,tolerance=row['tolerance'],status='PASS' if passed else 'FAIL'))
    check('historical_independent_area_mean8',len(areas)==8 and all(x['status']=='PASS' for x in areas),rows=len(areas),parameter_diameter_m=pa.diameter)
    boundaries=[]
    for row in old['sampling_boundaries']:
        p=m.CircularParameters(**row['inputs_SI'])
        value=s.prepare_profile(p,row['count']) if row['kind']=='profile' else s.prepare_screen(p,row['count'])
        good=(value.model.status.value==row['model'] and value.sampling.status.value==row['sampling'] and (value.data is not None)==row['data_present'] and value.sampling.required_count==row['required'])
        boundaries.append(dict(name=row['name'],input=row,actual_model=value.model.status.value,actual_sampling=value.sampling.status.value,data_present=value.data is not None,required=value.sampling.required_count,status='PASS' if good else 'FAIL'))
    check('historical_sampling_boundaries14',len(boundaries)==14 and all(x['status']=='PASS' for x in boundaries),rows=len(boundaries))
    for values in [(550,100,1),(633,200,2),(450,150,1.5),(450,300,1)]:
        p=m.CircularParameters.from_display_units(*values)
        screen=s.prepare_screen(p,383);profile=s.prepare_profile(p,1533)
        check('model_valid_'+str(values),m.assess_model(p).status==m.ModelStatus.VALID,F=m.fresnel_number(p))
        check('center_and_first_dark_'+str(values),m.intensity(p,0.,0.)==1. and m.intensity(p,m.first_dark_radius(p),0.)<1e-26,first_dark_radius_m=m.first_dark_radius(p),center=float(m.intensity(p,0.,0.)))
        if values==(450,300,1):
            check('screen383_F_boundary_correctly_paused',screen.data is None and screen.sampling.status==s.DisplayStatus.UNDERSAMPLED and screen.sampling.required_count==566,required=screen.sampling.required_count,provided=383,F=m.fresnel_number(p),contract='Physical validity and display sampling are separate gates')
        else:
            d=screen.data;a=d.pixel_mean
            check('screen383_'+str(values),a.shape==(383,383) and np.isfinite(a).all() and np.all((a>=0)&(a<=1)) and np.max(np.abs(a-a[::-1,:]))<=5e-14 and np.max(np.abs(a-a.T))<=5e-14,shape=list(a.shape),min=float(a.min()),max=float(a.max()),center_pixel_mean=float(a[191,191]),value_kind=d.value_kind)
        line=profile.data
        check('linear_profile1533_'+str(values),len(line.x)==1533 and line.x[line.center_index]==0. and line.intensity[line.center_index]==1. and np.max(np.abs(line.intensity-line.intensity[::-1]))<=5e-14 and not line.intensity.flags.writeable,points=len(line.x),value_kind=line.value_kind)
    pf=m.CircularParameters.from_display_units(450,300,1)
    check('F_boundary_valid',m.assess_model(pf).status==m.ModelStatus.VALID,F=m.fresnel_number(pf))
    check('F_next_diameter_invalid',m.assess_model(replace(pf,diameter=math.nextafter(pf.diameter,math.inf))).status==m.ModelStatus.INVALID)
    p=m.CircularParameters()
    check('radial_gate_exact',math.isfinite(m.intensity(p,.05,0.)))
    reject('radial_gate_nextfloat',lambda:m.intensity(p,math.nextafter(.05,math.inf),0.),m.CircularModelError)
    for vals,label in [((550,100,1),'FIRST_RING_FULL'),((750,20,.5),'FIRST_RING_PARTIAL'),((750,20,3),'FIRST_RING_OUTSIDE_VIEW')]:
        pp=m.CircularParameters.from_display_units(*vals)
        check('ring_coverage_'+label,m.first_ring_visibility(pp).value==label,inputs=vals,actual=m.first_ring_visibility(pp).value,first_dark_radius=m.first_dark_radius(pp),half_span=m.observation_half_span(pp))
    for z,n in [(.5,31),(.99,31),(1.,31),(1.1,63),(1.1,351),(1.131370849898476,351)]:
        pp=m.CircularParameters.from_display_units(550,20,z)
        value=s.prepare_screen(pp,n)
        check('F01_public_corner_'+str((z,n)),value.data is not None and np.isfinite(value.data.pixel_mean).all(),inputs=[z,n],historical_original_failure_preserved=True)
    
    check('over383_budget_no_allocation',s.prepare_screen(p,384).data is None and 'budget' in s.prepare_screen(p,384).sampling.reason)
    
    return {"status":"PASS","current_checks":len(checks),"checks":checks,"reference_rows1473":numeric,"independent_integral21":integral,"physical8":physical,"area8":areas,"boundaries14":boundaries,"maximum_errors":maximum,"original_tolerance_policy":"5e-14 and unchanged per-row historical bounds","historical_original_234_status":old["status"],"full234":"NOT_RUN","qt_pdf_checks":"NOT_RUN"}
def _init_api():
    global SYSTEM,K,P,V,HANDLE
    SYSTEM=Path(C["system_directory"])
    K=ctypes.WinDLL(str(SYSTEM/"kernel32.dll"),use_last_error=True)
    P=ctypes.WinDLL(str(SYSTEM/"psapi.dll"),use_last_error=True)
    V=ctypes.WinDLL(str(SYSTEM/"version.dll"),use_last_error=True)
    K.GetCurrentProcess.argtypes=[];K.GetCurrentProcess.restype=W.HANDLE
    P.EnumProcessModulesEx.argtypes=[W.HANDLE,ctypes.POINTER(W.HMODULE),W.DWORD,ctypes.POINTER(W.DWORD),W.DWORD];P.EnumProcessModulesEx.restype=W.BOOL
    P.GetModuleFileNameExW.argtypes=[W.HANDLE,W.HMODULE,W.LPWSTR,W.DWORD];P.GetModuleFileNameExW.restype=W.DWORD
    V.GetFileVersionInfoSizeW.argtypes=[W.LPCWSTR,ctypes.POINTER(W.DWORD)];V.GetFileVersionInfoSizeW.restype=W.DWORD
    V.GetFileVersionInfoW.argtypes=[W.LPCWSTR,W.DWORD,W.DWORD,W.LPVOID];V.GetFileVersionInfoW.restype=W.BOOL
    V.VerQueryValueW.argtypes=[W.LPCVOID,W.LPCWSTR,ctypes.POINTER(ctypes.c_void_p),ctypes.POINTER(W.UINT)];V.VerQueryValueW.restype=W.BOOL
    HANDLE=K.GetCurrentProcess()


def _initialize():
    global C,MODE,LABEL,AUDIT,RUNTIME,RESULT,SYSTEM,K,P,V,HANDLE
    if C is not None:return
    require(len(sys.argv)>=4 and sys.argv[1]=="--lf-diagnostic","invalid diagnostic invocation")
    MODE=sys.argv[2];require(MODE in ("science","gui-pdf"),"unapproved diagnostic mode")
    C=json.loads(Path(sys.argv[3]).read_text(encoding="utf-8"))
    RUNTIME=Path(sys.executable).resolve().parent;AUDIT=Path(C["audit"]);LABEL="frozen-"+MODE
    C["runtime"]=str(RUNTIME);C["source"]=str(RUNTIME);C["science_source"]=str(RUNTIME/"Runtime"/"science-source")
    C["references"]=[{"Path":str(RUNTIME/"Runtime"/"science-data"/r["name"]),"SHA256":r["sha256"]} for r in C["reference_inputs"]]
    RESULT={"mode":MODE,"label":LABEL,"pid":os.getpid(),"ppid":os.getppid(),"status":"STARTED","events":[],"module_snapshots":[]}
    require(getattr(sys,"frozen",False) and canon(sys._MEIPASS)==canon(RUNTIME/"Runtime"),"not expected Runtime-subdirectory onedir frozen layout")
    require(sys.version_info[:3]==(3,12,16) and struct.calcsize("P")==8,"frozen interpreter mismatch")
    require(sha(sys.executable)==C["exe_sha256"],"frozen executable changed")
    _init_api()
    K.GetConsoleWindow.argtypes=[]
    K.GetConsoleWindow.restype=W.HWND
    console_hwnd=K.GetConsoleWindow()
    RESULT["console_observation"]={"api":"GetConsoleWindow","hwnd":int(console_hwnd) if console_hwnd else 0,"attached":bool(console_hwnd),"utc":datetime.datetime.now(datetime.timezone.utc).isoformat(),"monotonic_ns":time.perf_counter_ns(),"scope":"Current-process console association; not a visual screenshot","last_error":"NOT_APPLICABLE_ZERO_MEANS_NO_ASSOCIATED_CONSOLE"}
    require(not console_hwnd,"windowed executable unexpectedly has an associated console")
def early_probe():
    _initialize()
    RESULT["identity"]={"executable":sys.executable,"sha256":sha(sys.executable),"prefix":sys.prefix,"base_prefix":sys.base_prefix,"MEIPASS":sys._MEIPASS,"version":sys.version,"architecture_bits":64}
    RESULT["environment_begin"]=environment()
    modules("earliest-python-custom-runtimehook")
def gui_pdf():
    from PySide6.QtCore import QCoreApplication,qVersion
    from PySide6.QtGui import QFont,QFontInfo,QGuiApplication
    from PySide6.QtWidgets import QApplication
    from lightfringe.airy_pdf_gui import AiryPdfMainWindow
    from lightfringe import report,circular_report
    from zoneinfo import ZoneInfo
    require(QApplication.instance() is None,"unexpected existing QApplication")
    app=QApplication(sys.argv[:1]);app.setApplicationName("光纹 LightFringe");app.setFont(QFont("Microsoft YaHei UI",10));app.setStyle("Fusion")
    require(QGuiApplication.platformName()=="windows","GUI did not load native Windows platform")
    font=QFontInfo(app.font()).family()
    require(font=="Microsoft YaHei UI","requested font substituted: "+font)
    require(datetime.datetime(2026,1,1,tzinfo=ZoneInfo("Asia/Shanghai")).utcoffset()==datetime.timedelta(hours=8),"timezone data missing")
    window=None;rows=[]
    try:
        window=AiryPdfMainWindow();window.show();app.processEvents()
        modules("native-main-window")
        for index,name in enumerate(["single-slit","double-slit","multi-slit","circular"]):
            window.mode.setCurrentIndex(index)
            if index in (0,1):window._load_values((550,30,150,1.));window._changed()
            else:window.restore_defaults()
            deadline=time.monotonic()+15
            while True:
                app.processEvents()
                if index<3:
                    ready=window._report_is_current() and window.view.data is not None and not window.view.error and bool(window.view.paint_times_ms)
                else:
                    view=window.airy_view
                    ready=view.state=="DISPLAY_VALID" and view.result is not None and view._presented_revision==view.result.request.revision
                if ready:break
                require(time.monotonic()<deadline,"GUI readiness deadline: "+name)
                time.sleep(.01)
            snapshot=window.report_snapshot()
            pdf=AUDIT/(name+".pdf");require(not pdf.exists(),"PDF output already exists")
            ledger={}
            if index==3:circular_report.write_pdf(snapshot,pdf,layout_audit=ledger)
            else:report.write_pdf(snapshot,pdf)
            data=pdf.read_bytes()
            require(len(data)>1000 and data.startswith(b"%PDF-") and data.rstrip().endswith(b"%%EOF"),"invalid PDF envelope")
            pages=len(re.findall(rb"/Type\s*/Page(?:\s|/|>)",data))
            require(pages==(1 if index<3 else 2) or (index==3 and pages==3),"unexpected PDF page count")
            image=AUDIT/(name+".png");require(not image.exists(),"image output exists")
            require(window.grab().save(str(image),"PNG"),"GUI capture failed")
            rows.append({"mode":name,"index":index,"gui_ready":True,"pdf":str(pdf),"pdf_sha256":sha(pdf),"pdf_bytes":len(data),"pdf_pages":pages,"layout_ledger":ledger,"screenshot":str(image),"screenshot_sha256":sha(image)})
            emit("GUI_PDF_MODE_PASS",mode=name,pdf_pages=pages)
        RESULT["gui_pdf"]={"status":"PASS","platform":QGuiApplication.platformName(),"qt_version":qVersion(),"font":font,"timezone":"Asia/Shanghai","modes":rows,"owner_visual_acceptance":"NOT_RUN"}
        modules("after-gui-and-four-pdf",True)
    finally:
        if window is not None:
            window.close();app.processEvents()
            closed=window.airy_view.closed
            running=window.airy_view._thread.isRunning()
            RESULT["gui_close"]={"closed":closed,"worker_running":running}
            require(closed and not running,"original GUI shutdown not complete")
        app.quit()
def main():
    try:
        _initialize();emit("BEGIN_FROZEN",mode=MODE)
        if MODE=="science":
            import numpy as np
            import scipy
            compatibility(np,scipy);RESULT["science"]=scientific_checks(np,scipy);modules("after-frozen-science",True)
        else:
            import numpy as np
            import scipy
            compatibility(np,scipy);gui_pdf()
        RESULT["environment_end"]=environment();RESULT["status"]="PASS_WITH_ENVIRONMENT_CAVEAT" if RESULT.get("external_environment_assessment",{}).get("observed") else "PASS";emit("COMPLETE_FROZEN",status=RESULT["status"])
    except BaseException as exc:
        RESULT["status"]="FAIL";RESULT["error"]={"type":type(exc).__name__,"message":str(exc),"traceback":traceback.format_exc()}
        traceback.print_exc();emit("STOP_FROZEN",error=str(exc))
    save_new(LABEL+"-result.json",RESULT)
    return 0 if RESULT["status"] in ("PASS","PASS_WITH_ENVIRONMENT_CAVEAT") else 1
