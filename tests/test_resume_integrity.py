import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np
import soundfile as sf

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "example"))
from audio_clean import durable_replace
from tts_book import _verified_file, _write_manifest


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


if __name__ == "__main__":
    unittest.main()
