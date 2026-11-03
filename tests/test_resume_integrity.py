import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
import soundfile as sf

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from audio_clean import durable_replace
from tts_book import _verified_file, _wait_for_vram, _write_manifest


class ResumeIntegrityTest(unittest.TestCase):
    def test_only_matching_intact_audio_is_resumed(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "chapter.flac"
            temporary = Path(directory) / "chapter.tmp.flac"
            sf.write(temporary, np.sin(np.arange(22050) / 20) * 0.25, 22050, subtype="PCM_16")
            _write_manifest(str(output) + ".manifest.json", "settings-a", temporary)
            durable_replace(temporary, output)
            self.assertTrue(_verified_file(output, "settings-a"))
            self.assertFalse(_verified_file(output, "settings-b"))
            damaged = bytearray(output.read_bytes())
            damaged[-10] ^= 0xFF
            output.write_bytes(damaged)
            self.assertFalse(_verified_file(output, "settings-a"))

    def test_low_vram_waits_until_memory_is_available(self):
        mib = 1024 * 1024

        class Cuda:
            def __init__(self):
                self.free = iter([500, 500, 900])
                self.cleared = 0

            def mem_get_info(self, device):
                return next(self.free) * mib, 8000 * mib

            def empty_cache(self):
                self.cleared += 1

        cuda = Cuda()
        with patch("tts_book.time.sleep") as sleep:
            _wait_for_vram(cuda, "cuda:0", 768)
        self.assertEqual(cuda.cleared, 1)
        sleep.assert_called_once_with(30)


if __name__ == "__main__":
    unittest.main()
