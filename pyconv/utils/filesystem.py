import os
import shutil
import string
import ctypes

def free_gb(path: str) -> float:
    try:
        _, _, free = shutil.disk_usage(path)
        return free / (1024**3)
    except Exception:
        return -1.0

def detect_network_drives() -> list[str]:
    drives = []
    try:
        bitmask = ctypes.windll.kernel32.GetLogicalDrives()
        for letter in string.ascii_uppercase:
            if bitmask & 1:
                drive = f"{letter}:\\"
                # GetDriveTypeW 4 is DRIVE_REMOTE
                if ctypes.windll.kernel32.GetDriveTypeW(drive) == 4:
                    drives.append(drive)
            bitmask >>= 1
    except Exception:
        pass
    return drives
