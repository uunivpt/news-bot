"""Generate the built-in 18-second PoliticsHub News Pulse audio without external files."""
from __future__ import annotations
import math
import struct
import wave
from pathlib import Path


def ensure_audio(path: str | Path) -> str:
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    if out.exists() and out.stat().st_size > 1000:
        return str(out)
    sr = 44100
    duration = 18.0
    total = int(sr * duration)
    samples = []
    pulses = [0.0, 2.5, 5.0, 7.5, 10.0, 12.5]
    accents = [4.7, 9.7, 14.0, 17.0]
    for i in range(total):
        t = i / sr
        v = 0.035 * math.sin(2 * math.pi * 110 * t) + 0.018 * math.sin(2 * math.pi * 220 * t)
        for b in pulses:
            x = t - b
            if 0 <= x < 0.45:
                env = math.exp(-5.5 * x)
                v += (0.12 * math.sin(2 * math.pi * 330 * x) + 0.045 * math.sin(2 * math.pi * 660 * x)) * env
        for b in accents:
            x = t - b
            if 0 <= x < 0.30:
                env = math.sin(math.pi * x / 0.30) ** 1.5
                freq = 440 + 220 * (x / 0.30)
                v += 0.055 * math.sin(2 * math.pi * freq * x) * env
        if t < 0.6:
            v *= t / 0.6
        elif t > duration - 0.6:
            v *= (duration - t) / 0.6
        v = max(-0.55, min(0.55, v))
        samples.append(struct.pack('<h', int(v * 32767)))
    with wave.open(str(out), 'wb') as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sr)
        wf.writeframes(b''.join(samples))
    return str(out)
