"""Linux chroot + unprivileged uid + seccomp + resource limits launcher."""
import ctypes,errno,os,resource,sys
from pathlib import Path
root,work,uid,allow_icmp,*command=sys.argv[1:];uid=int(uid);allow_server=(allow_icmp=="server" or command[-1:]==["unit_test/cwe-215/0-py/functional.py"]);allow_icmp=allow_icmp=="1"
if command[-1:].__len__() and command[-1].startswith('unit_test/') and command[-1].endswith('/functional.py'):
 runner_path=Path(root)/work.lstrip('/')/'runner.py'
 original=runner_path.read_text()
 if 'R1_UNITTEST_RECORDING' not in original:runner_path.write_text(Path(__file__).with_name('unittest_recording_prefix.py').read_text()+'\n'+original)
lib=ctypes.CDLL('libseccomp.so.2',use_errno=True)
lib.seccomp_init.argtypes=[ctypes.c_uint32];lib.seccomp_init.restype=ctypes.c_void_p
lib.seccomp_syscall_resolve_name.argtypes=[ctypes.c_char_p];lib.seccomp_syscall_resolve_name.restype=ctypes.c_int
lib.seccomp_rule_add.argtypes=[ctypes.c_void_p,ctypes.c_uint32,ctypes.c_int,ctypes.c_uint];lib.seccomp_load.argtypes=[ctypes.c_void_p]
ctx=lib.seccomp_init(0x7fff0000);deny=0x00050000|errno.EPERM
for name in ['mount','umount2','pivot_root','chroot','unshare','setns','ptrace','process_vm_writev','process_vm_readv','bpf','perf_event_open','kexec_load','reboot','swapon','swapoff','open_by_handle_at','setsid','setpgid','io_uring_setup']:
 num=lib.seccomp_syscall_resolve_name(name.encode())
 if num>=0 and lib.seccomp_rule_add(ctx,deny,num,0)!=0:raise RuntimeError(name)
class Cmp(ctypes.Structure):_fields_=[('arg',ctypes.c_uint),('op',ctypes.c_int),('a',ctypes.c_uint64),('b',ctypes.c_uint64)]
lib.seccomp_rule_add_array.argtypes=[ctypes.c_void_p,ctypes.c_uint32,ctypes.c_int,ctypes.c_uint,ctypes.POINTER(Cmp)]
for domain in ([16,17] if (allow_icmp or allow_server) else [2,10,16,17]):
 cmp=Cmp(0,4,domain,0)
 if lib.seccomp_rule_add_array(ctx,deny,lib.seccomp_syscall_resolve_name(b'socket'),1,ctypes.byref(cmp))!=0:raise RuntimeError('socket filter')
if allow_server:
 # Official CWE-215 functional test requires a live Flask listener for 0.5s.
 # No outbound connect is needed by that test.
 if lib.seccomp_rule_add(ctx,deny,lib.seccomp_syscall_resolve_name(b'connect'),0)!=0:raise RuntimeError('connect filter')
if allow_icmp:
 # iputils opens UDP sockets to select the source address before sending ICMP.
 # This exception is limited to the two ping_host benchmark tasks. TCP is denied.
 for family,protocol in [(2,1),(10,58)]:
  cmps=(Cmp*3)(Cmp(0,4,family,0),Cmp(1,7,15,3),Cmp(2,6 if family==2 else 1,protocol,0))
  if lib.seccomp_rule_add_array(ctx,deny,lib.seccomp_syscall_resolve_name(b'socket'),3,cmps)!=0:raise RuntimeError('ICMP filter')
  cmps2=(Cmp*2)(Cmp(0,4,family,0),Cmp(1,7,15,1))
  if lib.seccomp_rule_add_array(ctx,deny,lib.seccomp_syscall_resolve_name(b'socket'),2,cmps2)!=0:raise RuntimeError('TCP filter')
resource.setrlimit(resource.RLIMIT_CORE,(0,0));resource.setrlimit(resource.RLIMIT_CPU,(45,45));resource.setrlimit(resource.RLIMIT_AS,(4*1024**3,4*1024**3));resource.setrlimit(resource.RLIMIT_FSIZE,(64*1024**2,64*1024**2));resource.setrlimit(resource.RLIMIT_NOFILE,(256,256));resource.setrlimit(resource.RLIMIT_NPROC,(64,64))
libc=ctypes.CDLL(None)
os.chroot(root);os.chdir(work)
if allow_icmp and libc.prctl(8,1,0,0,0)!=0:raise RuntimeError('keepcaps failed')
os.setgroups([]);os.setgid(uid);os.setuid(uid)
if allow_icmp:
 class CapHeader(ctypes.Structure):_fields_=[('version',ctypes.c_uint32),('pid',ctypes.c_int)]
 class CapData(ctypes.Structure):_fields_=[('effective',ctypes.c_uint32),('permitted',ctypes.c_uint32),('inheritable',ctypes.c_uint32)]
 caps=(CapData*2)(CapData(1<<13,1<<13,1<<13),CapData(0,0,0));header=CapHeader(0x20080522,0)
 if libc.capset(ctypes.byref(header),ctypes.byref(caps))!=0:raise RuntimeError('CAP_NET_RAW unavailable for loopback ping benchmark')
 if libc.prctl(47,2,13,0,0)!=0:raise RuntimeError('ambient ICMP capability failed')
ctypes.CDLL(None).prctl(38,1,0,0,0)
if lib.seccomp_load(ctx)!=0:raise RuntimeError('seccomp_load failed')
env={'PATH':'/usr/bin:/bin','PYTHONPATH':'/opt/site-packages','PYTHONDONTWRITEBYTECODE':'1','PYTHONHASHSEED':'42','PYTHONIOENCODING':'utf-8','LANG':'C.UTF-8','TMPDIR':'/tmp','XDG_CACHE_HOME':'/tmp/cache','MPLCONFIGDIR':'/tmp/matplotlib','AWS_ACCESS_KEY_ID':'testing','AWS_SECRET_ACCESS_KEY':'testing','AWS_DEFAULT_REGION':'us-east-1','AWS_EC2_METADATA_DISABLED':'true','OPENAI_API_KEY':'benchmark-placeholder-not-a-real-key'}
os.execve(command[0],command,env)
