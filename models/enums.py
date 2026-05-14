"""Enums for PYConv — replaces scattered string literals and magic numbers."""

from enum import Enum


class JobStatus(Enum):
    PENDING = "pending"
    SCANNING = "scanning"
    DOWNLOADING = "downloading"
    ENCODING = "encoding"
    UPLOADING = "uploading"
    DONE = "done"
    FAILED = "failed"
    SKIPPED = "skipped"
    RETRYING = "retrying"


class GPUType(Enum):
    NVIDIA = "nvidia"
    INTEL = "intel"
    AMD = "amd"
    CPU = "cpu"


class EncoderType(Enum):
    AV1NVENC = "av1nvenc"
    HEVCNVENC = "hevcnvenc"
    AV1QSV = "av1qsv"
    HEVCQSV = "hevcqsv"
    AV1AMF = "av1amf"
    HEVCAMF = "hevcamf"
    LIBSVTAV1 = "libsvtav1"
    LIBX265 = "libx265"
    LIBAOM_AV1 = "libaom-av1"
    LIBX264 = "libx264"

    @classmethod
    def from_str(cls, value: str) -> "EncoderType":
        """Parse encoder string from GUI labels like 'av1nvenc NVIDIA AV1'."""
        key = value.split()[0].lower()
        for member in cls:
            if member.value == key:
                return member
        raise ValueError(f"Unknown encoder: {value!r}")


class UploadStatus(Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    VERIFIED = "verified"
    FAILED = "failed"
    SHA_MISMATCH = "sha_mismatch"
    SIZE_MISMATCH = "size_mismatch"


class ProbeStatus(Enum):
    OK = "ok"
    CORRUPT = "corrupt"
    RAWVIDEO = "rawvideo"  # AVI z błędnym FOURCC — objaw decrawvideo
    NAL_ERROR = "nal_error"  # H.264 AnnexB / AVCC mismatch
    UNREADABLE = "unreadable"


class RepairMode(Enum):
    FOURCC_REMUX = "fourcc_remux"  # Wariant 1: AVI→MKV copy
    FOURCC_MPEG4 = "fourcc_mpeg4"  # Wariant 2: force mpeg4 decoder
    FOURCC_H264_LOSSLESS = "fourcc_h264_lossless"  # Wariant 3: libx264 crf=0
    ANNEXB_BSF = "annexb_bsf"  # extractextradata / h264_mp4toannexb
    ANNEXB_IGNORE_ERR = "annexb_ignore_err"  # -fflags discardcorrupt -err_detect ignore_err
    NONE = "none"
