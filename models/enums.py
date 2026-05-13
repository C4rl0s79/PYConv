"""Enumerations used across the PYConv pipeline."""
from enum import Enum, auto


class JobStatus(Enum):
    PENDING = auto()
    SCANNING = auto()
    DOWNLOADING = auto()
    ENCODING = auto()
    UPLOADING = auto()
    VERIFYING = auto()
    DONE = auto()
    SKIPPED = auto()
    ERROR = auto()
    CANCELLED = auto()


class GPUType(Enum):
    NVIDIA = "nvidia"
    INTEL = "intel"
    AMD = "amd"
    CPU = "cpu"
    UNKNOWN = "unknown"


class EncoderType(Enum):
    AV1_NVENC = "av1_nvenc"
    HEVC_NVENC = "hevc_nvenc"
    AV1_QSV = "av1_qsv"
    HEVC_QSV = "hevc_qsv"
    AV1_AMF = "av1_amf"
    HEVC_AMF = "hevc_amf"
    LIBX265 = "libx265"
    LIBAOM_AV1 = "libaom-av1"
    LIBSVTAV1 = "libsvtav1"

    @classmethod
    def from_label(cls, label: str) -> "EncoderType":
        """Parse from GUI display label like 'av1_nvenc (NVIDIA AV1)'."""
        key = label.split()[0].lower()
        for member in cls:
            if member.value == key:
                return member
        raise ValueError(f"Unknown encoder label: {label!r}")


class UploadStatus(Enum):
    PENDING = auto()
    IN_PROGRESS = auto()
    DONE = auto()
    FAILED = auto()
    STALLED = auto()
    CANCELLED = auto()


class ProbeStatus(Enum):
    OK = auto()
    ERROR = auto()
    TIMEOUT = auto()
    UNSUPPORTED = auto()


class RepairMode(Enum):
    NONE = auto()
    ANNEXB = auto()        # Annex B → AVCC remux
    FOURCC = auto()        # AVI bad FOURCC fix
    FOURCC_FORCE = auto()  # Force mpeg4 decoder
    FOURCC_LOSSLESS = auto()  # Lossless H.264 intermediate
