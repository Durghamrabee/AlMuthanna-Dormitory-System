import atexit
import hashlib
import os


def acquire(data_dir):
    if os.name != "nt":
        return True
    import ctypes
    key = hashlib.sha256(os.path.normcase(str(data_dir)).encode()).hexdigest()[:24]
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_bool, ctypes.c_wchar_p]
    kernel.CreateMutexW.restype = ctypes.c_void_p
    kernel.CloseHandle.argtypes = [ctypes.c_void_p]
    handle = kernel.CreateMutexW(None, True, "Local\\AlMuthannaDormitory-" + key)
    if not handle:
        raise OSError("تعذر إنشاء قفل التشغيل المحلي.")
    if ctypes.get_last_error() == 183:
        kernel.CloseHandle(handle)
        return False
    atexit.register(kernel.CloseHandle, handle)
    return True
