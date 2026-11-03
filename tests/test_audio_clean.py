import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np
import soundfile as sf

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from audio_clean import smooth_file


class SmoothAudioTest(unittest.TestCase):
    def test_preserves_speech_harmonics_and_reduces_isolated_click(self):
        sr = 22050
        time = np.arange(sr * 2) / sr
        # High-frequency harmonics should not be mistaken for isolated clicks.
        signal = (0.4 * np.sin(2 * np.pi * 200 * time)
                  + 0.18 * np.sin(2 * np.pi * 400 * time)
                  + 0.08 * np.sin(2 * np.pi * 5000 * time))
        click = signal.copy()
        click[sr] += 0.7
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            raw = directory / "raw.wav"
            damaged = directory / "click.wav"
            smooth = directory / "smooth.wav"
            corrected = directory / "corrected.wav"
            sf.write(raw, signal, sr, subtype="FLOAT")
            sf.write(damaged, click, sr, subtype="FLOAT")
            smooth_file(raw, smooth)
            smooth_file(damaged, corrected)
            baseline, out_sr = sf.read(smooth)
            fixed, fixed_sr = sf.read(corrected)

        self.assertEqual((out_sr, fixed_sr), (sr, sr))
        self.assertEqual((len(baseline), len(fixed)), (len(signal), len(signal)))
        self.assertGreater(np.sqrt(np.mean(baseline ** 2)), 0.9 * np.sqrt(np.mean(signal ** 2)))
        self.assertLess(abs(fixed[sr] - baseline[sr]), 0.1)

    def test_loud_high_frequency_is_not_erased(self):
        sr = 22050
        signal = 0.7 * np.sin(2 * np.pi * 5000 * np.arange(sr) / sr)
        with tempfile.TemporaryDirectory() as directory:
            raw = Path(directory) / "raw.wav"
            smooth = Path(directory) / "smooth.wav"
            sf.write(raw, signal, sr, subtype="FLOAT")
            smooth_file(raw, smooth)
            result, _ = sf.read(smooth)
        self.assertGreater(np.sqrt(np.mean(result ** 2)), 0.65 * np.sqrt(np.mean(signal ** 2)))

    def test_smoothed_flac_stays_16_bit(self):
        sr = 22050
        signal = 0.4 * np.sin(2 * np.pi * 200 * np.arange(sr) / sr)
        with tempfile.TemporaryDirectory() as directory:
            raw = Path(directory) / "raw.flac"
            smooth = Path(directory) / "smooth.flac"
            sf.write(raw, signal, sr, subtype="PCM_16")
            smooth_file(raw, smooth)
            info = sf.info(smooth)
            self.assertEqual(info.subtype, "PCM_16")
            self.assertEqual((info.frames, info.samplerate), (len(signal), sr))

    def test_failed_filter_does_not_overwrite_destination(self):
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            broken = directory / "invalid.wav"
            output = directory / "output.wav"
            broken.write_bytes(b"not audio")
            output.write_bytes(b"existing output")
            with self.assertRaises(subprocess.CalledProcessError):
                smooth_file(broken, output)
            self.assertEqual(output.read_bytes(), b"existing output")


if __name__ == "__main__":
    unittest.main()
