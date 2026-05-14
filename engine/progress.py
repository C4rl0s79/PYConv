"""ProgressTracker — mapuje per-plik progress do globalnego total-bar.

Thread-safe. Zachowana 1:1 logika z monolitu:
  - LOCAL: 1 slot = 1 plik (tylko faza 'convert')
  - NETWORK: 1 slot = 3 fazy (copyin 0-33, convert 33-66, copyout 66-100)
Dwa GPU piszą równocześnie do peaks[], lock chroni sumę.
"""
from __future__ import annotations
import threading


class ProgressTracker:
    """Maps per-file phase progress (0–100) → global total bar (0–100).

    Thread-safe: dwa GPU mogą wywoływać update() równocześnie.
    """

    def __init__(self, total_files: int, network: bool = False):
        self.N = max(total_files, 1)
        self.network = network
        self.slot = 100.0 / self.N
        self.lock = threading.Lock()
        self.peaks = [0.0] * self.N

    def update(self, file_idx: int, phase: str, phase_pct: float) -> float:
        """Zwraca aktualny global percent (0–100).

        Fazy LOCAL: 'convert'
        Fazy NETWORK: 'copyin', 'convert', 'copyout'
        """
        p = max(0.0, min(100.0, phase_pct))
        base = file_idx * self.slot
        third = self.slot / 3.0

        if not self.network:
            new_val = base + p * self.slot / 100.0
        else:
            if phase == "copyin":
                new_val = base + p * third / 100.0
            elif phase == "convert":
                new_val = base + third + p * third / 100.0
            else:  # copyout
                new_val = base + 2 * third + p * third / 100.0

        with self.lock:
            if new_val > self.peaks[file_idx]:
                self.peaks[file_idx] = new_val
            total = sum(self.peaks)

        return min(total, 100.0)
