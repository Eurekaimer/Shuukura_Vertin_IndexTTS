"""Optional, conservative smoothing for rendered speech.

FFmpeg's autoregressive declick filter interpolates isolated impulsive noise.
A mild high-shelf cut reduces harsh treble without removing speech segments.
Neither operation can remove vocoder artifacts already embedded in a voice.
"""

import argparse
import os
from pathlib import Path
import subprocess
import tempfile

# A higher declick threshold is less aggressive; overlap-save leaves unflagged
# samples unchanged before the gentle treble adjustment.
SMOOTH_FILTER = "adeclick=threshold=10:method=save,treble=gain=-2:frequency=6500"


def durable_replace(source, destination):
    """Commit a completed file and its directory entry before returning."""
    with open(source, "rb") as f:
        os.fsync(f.fileno())
    os.replace(source, destination)
    directory = os.path.dirname(os.path.abspath(destination))
    fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def smooth_file(source, destination):
    """Write a smoothed copy, leaving the input untouched on failure."""
    source = Path(source)
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        prefix=".smooth-", suffix=destination.suffix, dir=destination.parent, delete=False
    ) as temp:
        temp_path = Path(temp.name)
    format_args = ["-sample_fmt", "s16"] if destination.suffix.lower() == ".flac" else []
    try:
        subprocess.run(
            ["ffmpeg", "-nostdin", "-v", "error", "-y", "-i", str(source),
             "-af", SMOOTH_FILTER, *format_args, str(temp_path)],
            check=True,
        )
        durable_replace(temp_path, destination)
    finally:
        temp_path.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("files", nargs="+")
    parser.add_argument("--inplace", action="store_true", help="replace each input after successful processing")
    args = parser.parse_args()
    for filename in args.files:
        source = Path(filename)
        destination = source if args.inplace else source.with_name(f"{source.stem}_smooth{source.suffix}")
        smooth_file(source, destination)
        print(f"{source} -> {destination}")


if __name__ == "__main__":
    main()
