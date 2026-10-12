#!/usr/bin/env python3
"""Small PS2 SPU ADPCM encoder used by SAAT PS2 Studio.

Source audio is decoded/resampled by FFmpeg into 16-bit stereo PCM. This module
encodes that PCM as interleaved PSX/SPU ADPCM frames for GTA SA PS2 radio stream
payloads (not the PC game's Ogg Vorbis format).
"""
from __future__ import annotations

import os
import shutil
import struct
import subprocess
import tempfile
import wave
import time

try:
    import numpy as np
except ImportError:  # dependency is installed by Setup_Dependencies.bat
    np = None

try:
    from numba import njit
except ImportError:  # dependency is installed by Setup_Dependencies.bat
    njit = None
from pathlib import Path
from typing import Callable, Optional

VAG_HEADER_SIZE = 0x30
VAG_MAGIC = b"VAGp"
FRAME_SAMPLES = 28
FRAME_BYTES = 16
# PSX SPU predictor coefficients, scaled by 64.
FILTERS = ((0, 0), (60, 0), (115, -52), (98, -55), (122, -60))
SUPPORTED_AUDIO_SUFFIXES = {
    ".wav", ".wave", ".mp3", ".flac", ".ogg", ".oga", ".opus", ".m4a",
    ".aac", ".wma", ".aiff", ".aif", ".ape", ".mp2", ".ac3", ".at3",
    ".at3p", ".caf", ".mp4", ".webm", ".mkv", ".mov",
}


class AudioEncodeError(RuntimeError):
    pass


def find_ffmpeg(preferred: str = "") -> Optional[str]:
    preferred = preferred.strip().strip('"')
    if preferred and (Path(preferred).is_file() or shutil.which(preferred)):
        return preferred
    return shutil.which("ffmpeg")


def _round_div(n: int, d: int) -> int:
    """Round n/d to nearest integer, symmetrically for negative numbers."""
    if n >= 0:
        return (n + d // 2) // d
    return -((-n + d // 2) // d)


def _clip16(x: int) -> int:
    return -32768 if x < -32768 else 32767 if x > 32767 else x


def _encode_frame(samples: list[int], hist1: int, hist2: int, flag: int) -> tuple[bytes, int, int]:
    """Encode exactly 28 mono samples into one 16-byte PSX ADPCM frame."""
    if len(samples) != FRAME_SAMPLES:
        samples = samples + [0] * (FRAME_SAMPLES - len(samples))

    best = None
    # Test each predictor. Estimate the quantiser scale from residuals using the
    # source history, then score with reconstructed output and retained history.
    for filt, (c1, c2) in enumerate(FILTERS):
        residuals = []
        prev2, prev1 = hist2, hist1
        for x in samples:
            pred = (prev1 * c1 + prev2 * c2 + 32) >> 6
            residuals.append(x - pred)
            prev2, prev1 = prev1, x
        peak = max((abs(r) for r in residuals), default=0)
        # PSX ADPCM's decoded nibble scale is 1 << (12 - shift), 1..4096.
        need = max(1, (peak + 6) // 7)
        factor = 1
        while factor < need and factor < 4096:
            factor <<= 1
        factor = min(4096, factor)
        shift = 12 - (factor.bit_length() - 1)

        qvals = []
        recon_hist1, recon_hist2 = hist1, hist2
        error = 0
        for x in samples:
            pred = (recon_hist1 * c1 + recon_hist2 * c2 + 32) >> 6
            q = _round_div(x - pred, factor)
            q = -8 if q < -8 else 7 if q > 7 else q
            decoded = _clip16(pred + q * factor)
            error += (x - decoded) * (x - decoded)
            qvals.append(q)
            recon_hist2, recon_hist1 = recon_hist1, decoded
        candidate = (error, filt, shift, qvals, recon_hist1, recon_hist2)
        if best is None or candidate[0] < best[0]:
            best = candidate

    assert best is not None
    _, filt, shift, qvals, out_h1, out_h2 = best
    frame = bytearray(FRAME_BYTES)
    frame[0] = (filt << 4) | (shift & 0x0F)
    frame[1] = flag & 0xFF
    for i in range(0, FRAME_SAMPLES, 2):
        lo = qvals[i] & 0x0F
        hi = qvals[i + 1] & 0x0F
        frame[2 + i // 2] = lo | (hi << 4)
    return bytes(frame), out_h1, out_h2


def _encode_pcm_frames(left: list[int], right: list[int], histories: list[list[int]], first_frame: bool) -> bytes:
    """Encode one chunk whose left/right sample arrays have the same length."""
    frame_count = (len(left) + FRAME_SAMPLES - 1) // FRAME_SAMPLES
    out = bytearray(frame_count * FRAME_BYTES * 2)
    out_pos = 0
    for frame_i in range(frame_count):
        a = left[frame_i * FRAME_SAMPLES:(frame_i + 1) * FRAME_SAMPLES]
        b = right[frame_i * FRAME_SAMPLES:(frame_i + 1) * FRAME_SAMPLES]
        # This stream format uses 0x02 for regular blocks and 0x06 for the
        # first block, matching the PS2 radio payload signature observed in the
        # supplied archive. Table length, not a VAGp end marker, ends a stream.
        flag_l = 0x06 if first_frame and frame_i == 0 else 0x02
        # GTA SA's stereo stream alternates one ADPCM frame per channel. The
        # stream's first frame is marked 0x06; the immediately following right
        # channel frame remains a normal 0x02 frame, matching the supplied PAK.
        f_l, histories[0][0], histories[0][1] = _encode_frame(a, histories[0][0], histories[0][1], flag_l)
        f_r, histories[1][0], histories[1][1] = _encode_frame(b, histories[1][0], histories[1][1], 0x02)
        out[out_pos:out_pos + FRAME_BYTES] = f_l
        out[out_pos + FRAME_BYTES:out_pos + 2 * FRAME_BYTES] = f_r
        out_pos += FRAME_BYTES * 2
    return bytes(out)


if njit is not None:
    @njit(cache=True)
    def _encode_channel_frame_numba(samples, group_index, channel, hist1, hist2,
                                    flag, out, out_offset, best_q, temp_q):
        """Encode one PSX ADPCM mono frame, searching all five predictor filters."""
        sample_frames = samples.size // 2
        frame_start = group_index * FRAME_SAMPLES
        best_error = 9223372036854775807
        best_filter = 0
        best_shift = 12
        best_hist1 = hist1
        best_hist2 = hist2

        for filt in range(5):
            if filt == 0:
                c1, c2 = 0, 0
            elif filt == 1:
                c1, c2 = 60, 0
            elif filt == 2:
                c1, c2 = 115, -52
            elif filt == 3:
                c1, c2 = 98, -55
            else:
                c1, c2 = 122, -60

            # Estimate quantizer shift using the original samples and the
            # reconstructed history inherited from the previous frame.
            peak = 0
            prev1, prev2 = hist1, hist2
            for j in range(FRAME_SAMPLES):
                pos = frame_start + j
                x = int(samples[pos * 2 + channel]) if pos < sample_frames else 0
                pred = (prev1 * c1 + prev2 * c2 + 32) >> 6
                residual = x - pred
                magnitude = -residual if residual < 0 else residual
                if magnitude > peak:
                    peak = magnitude
                prev2, prev1 = prev1, x

            need = max(1, (peak + 6) // 7)
            factor = 1
            shift = 12
            while factor < need and factor < 4096:
                factor <<= 1
                shift -= 1

            # Quantize/decode candidate and calculate its reconstruction error.
            recon1, recon2 = hist1, hist2
            error = 0
            for j in range(FRAME_SAMPLES):
                pos = frame_start + j
                x = int(samples[pos * 2 + channel]) if pos < sample_frames else 0
                pred = (recon1 * c1 + recon2 * c2 + 32) >> 6
                diff = x - pred
                if diff >= 0:
                    q = (diff + factor // 2) // factor
                else:
                    q = -((-diff + factor // 2) // factor)
                if q < -8:
                    q = -8
                elif q > 7:
                    q = 7
                decoded = pred + q * factor
                if decoded < -32768:
                    decoded = -32768
                elif decoded > 32767:
                    decoded = 32767
                delta = x - decoded
                error += delta * delta
                temp_q[j] = q
                recon2, recon1 = recon1, decoded

            if error < best_error:
                best_error = error
                best_filter = filt
                best_shift = shift
                best_hist1 = recon1
                best_hist2 = recon2
                for j in range(FRAME_SAMPLES):
                    best_q[j] = temp_q[j]

        out[out_offset] = (best_filter << 4) | (best_shift & 0x0F)
        out[out_offset + 1] = flag & 0xFF
        for j in range(0, FRAME_SAMPLES, 2):
            lo = best_q[j] & 0x0F
            hi = best_q[j + 1] & 0x0F
            out[out_offset + 2 + j // 2] = lo | (hi << 4)
        return best_hist1, best_hist2

    @njit(cache=True)
    def _encode_pcm_chunk_numba(samples, histories, first_frame):
        """Compiled high-quality encoder; preserves five-filter predictor search."""
        sample_frames = samples.size // 2
        group_count = (sample_frames + FRAME_SAMPLES - 1) // FRAME_SAMPLES
        out = np.zeros(group_count * FRAME_BYTES * 2, dtype=np.uint8)
        best_q = np.zeros(FRAME_SAMPLES, dtype=np.int8)
        temp_q = np.zeros(FRAME_SAMPLES, dtype=np.int8)
        lh1, lh2 = int(histories[0]), int(histories[1])
        rh1, rh2 = int(histories[2]), int(histories[3])
        for group in range(group_count):
            flag = 0x06 if first_frame and group == 0 else 0x02
            base = group * FRAME_BYTES * 2
            lh1, lh2 = _encode_channel_frame_numba(
                samples, group, 0, lh1, lh2, flag, out, base, best_q, temp_q
            )
            rh1, rh2 = _encode_channel_frame_numba(
                samples, group, 1, rh1, rh2, 0x02, out, base + FRAME_BYTES, best_q, temp_q
            )
        histories[0], histories[1] = lh1, lh2
        histories[2], histories[3] = rh1, rh2
        return out, histories
else:
    _encode_pcm_chunk_numba = None

def encode_pcm_wav_to_ps2_payload(pcm_wav: Path, output_raw: Path, sample_rate: int = 24000,
                                  progress: Optional[Callable[[str], None]] = None,
                                  cancel_event=None) -> dict:
    """Fast-vector encode normalized stereo PCM WAV as interleaved PS2 SPU ADPCM."""
    if np is None or njit is None:
        raise AudioEncodeError(
            "NumPy and Numba are required for fast, quality-preserving batch encoding. "
            "Run Setup_Dependencies.bat or install requirements.txt."
        )
    try:
        wf = wave.open(str(pcm_wav), "rb")
    except (wave.Error, OSError) as exc:
        raise AudioEncodeError(f"Could not read decoded PCM WAV: {exc}") from exc
    with wf:
        if wf.getnchannels() != 2 or wf.getsampwidth() != 2:
            raise AudioEncodeError("Internal PCM file must be 16-bit stereo WAV.")
        if wf.getframerate() != sample_rate:
            raise AudioEncodeError(f"Internal PCM rate is {wf.getframerate()} Hz, expected {sample_rate} Hz.")
        total_frames = wf.getnframes()
        if total_frames < 1:
            raise AudioEncodeError("The source audio contains no samples.")
        chunk_samples = FRAME_SAMPLES * 8192
        total_payload = 0
        done = 0
        last_report = -1
        histories = np.zeros(4, dtype=np.int64)
        output_raw.parent.mkdir(parents=True, exist_ok=True)
        with output_raw.open("wb") as out:
            while done < total_frames:
                if cancel_event is not None and cancel_event.is_set():
                    raise AudioEncodeError("Conversion cancelled by user.")
                want = min(chunk_samples, total_frames - done)
                if want < total_frames - done:
                    want = (want // FRAME_SAMPLES) * FRAME_SAMPLES
                raw = wf.readframes(want)
                if not raw:
                    break
                # WAV PCM is little-endian s16. Numba runs the original five-predictor
                # search in compiled code, avoiding the multi-hour pure-Python batch path.
                samples = np.frombuffer(raw, dtype="<i2")
                encoded, histories = _encode_pcm_chunk_numba(samples, histories, done == 0)
                encoded_bytes = encoded.tobytes()
                out.write(encoded_bytes)
                total_payload += len(encoded_bytes)
                done += len(samples) // 2
                if progress:
                    pct = min(100, int(done * 100 / total_frames))
                    # Report only when the visible percent changes, not for every chunk.
                    if pct != last_report:
                        progress(f"Encoding {pct}%")
                        last_report = pct
        if total_payload == 0:
            raise AudioEncodeError("The encoder produced no ADPCM output.")
        return {
            "sample_rate": sample_rate,
            "channels": 2,
            "pcm_frames": total_frames,
            "payload_bytes": total_payload,
            "duration_seconds": total_frames / sample_rate,
            "encoder": "Numba-compiled PSX ADPCM (five-predictor search)",
        }

def sys_byteorder_big() -> bool:
    import sys
    return sys.byteorder == "big"


def convert_audio_to_ps2_payload(source: Path, output_raw: Path, ffmpeg: str,
                                 sample_rate: int = 24000,
                                 progress: Optional[Callable[[str], None]] = None,
                                 cancel_event=None) -> dict:
    """Decode/resample via FFmpeg, then quickly encode PS2 SPU ADPCM."""
    if not source.is_file():
        raise AudioEncodeError(f"Source audio does not exist: {source}")
    if source.suffix.lower() not in SUPPORTED_AUDIO_SUFFIXES:
        raise AudioEncodeError(f"Unsupported audio filename extension: {source.suffix or '(none)'}")
    exe = find_ffmpeg(ffmpeg)
    if not exe:
        raise AudioEncodeError("FFmpeg was not found. Install FFmpeg or set its path in Audio Preparation.")
    if not 8000 <= sample_rate <= 48000:
        raise AudioEncodeError(f"Unsupported target sample rate: {sample_rate} Hz.")
    if np is None or njit is None:
        raise AudioEncodeError("NumPy and Numba are required for fast encoding. Run Setup_Dependencies.bat first.")
    output_raw.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="saatps2_encode_") as td:
        pcm_path = Path(td) / "normalized_pcm.wav"
        cmd = [
            exe, "-hide_banner", "-loglevel", "error", "-y", "-i", str(source),
            "-map", "0:a:0", "-vn", "-sn", "-dn", "-ac", "2", "-ar", str(sample_rate),
            "-sample_fmt", "s16", "-c:a", "pcm_s16le", "-f", "wav", str(pcm_path),
        ]
        if progress:
            progress("Decoding/resampling with FFmpeg")
        proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
        try:
            while proc.poll() is None:
                if cancel_event is not None and cancel_event.is_set():
                    proc.terminate()
                    try:
                        proc.wait(timeout=2)
                    except subprocess.TimeoutExpired:
                        proc.kill()
                        proc.wait()
                    raise AudioEncodeError("Conversion cancelled by user.")
                time.sleep(0.1)
            stderr = proc.stderr.read() if proc.stderr else ""
        finally:
            if proc.stderr:
                proc.stderr.close()
        if proc.returncode != 0 or not pcm_path.is_file():
            details = (stderr or "FFmpeg could not decode this source.")[-3000:]
            raise AudioEncodeError(f"FFmpeg decode/resample failed for {source.name}:\n{details}")
        meta = encode_pcm_wav_to_ps2_payload(pcm_path, output_raw, sample_rate, progress, cancel_event)
    meta["source"] = str(source)
    meta["encoded_file"] = str(output_raw)
    return meta

def wrap_vagp(payload_path: Path, output_vag: Path, sample_rate: int = 24000) -> None:
    """Create a VAGp wrapper around PSX ADPCM data for conventional VAG tracks."""
    payload = payload_path.read_bytes()
    if not payload or len(payload) % 16:
        raise AudioEncodeError("ADPCM payload size is not a multiple of 16 bytes.")
    header = bytearray(VAG_HEADER_SIZE)
    header[:4] = VAG_MAGIC
    struct.pack_into(">I", header, 0x04, 0x20)
    struct.pack_into(">I", header, 0x0C, len(payload))
    struct.pack_into(">I", header, 0x10, sample_rate)
    output_vag.write_bytes(bytes(header) + payload)
