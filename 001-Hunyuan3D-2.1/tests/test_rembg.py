"""Background-removal regression tests without model weights or GPU."""
import importlib.util
from pathlib import Path
from PIL import Image

import os
repo = Path(os.getenv("HY3D_TEST_REPO", str(Path(__file__).resolve().parents[1] / "modal-forge-Hunyuan3D-2.1")))
file = repo / "hy3dshape" / "hy3dshape" / "rembg.py"
spec = importlib.util.spec_from_file_location("hy3d_rembg_test", file)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
prepare_foreground = module.prepare_foreground


class FakeRemover:
    def __init__(self):
        self.calls = 0

    def __call__(self, image):
        self.calls += 1
        assert image.mode == "RGB"
        return Image.new("RGBA", image.size, (12, 34, 56, 0))


def run():
    cases = [
        ("RGB", Image.new("RGB", (8, 8), "white"), False, 1),
        ("opaque RGBA", Image.new("RGBA", (8, 8), (255, 255, 255, 255)), False, 1),
        ("transparent RGBA", Image.new("RGBA", (8, 8), (10, 20, 30, 0)), False, 0),
        ("partial alpha", Image.new("RGBA", (8, 8), (10, 20, 30, 150)), False, 0),
        ("force transparent", Image.new("RGBA", (8, 8), (10, 20, 30, 0)), True, 1),
        ("grayscale", Image.new("L", (8, 8), 128), False, 1),
    ]
    for name, source, force, expected in cases:
        remover = FakeRemover()
        output = prepare_foreground(source, remover, force=force)
        assert remover.calls == expected, (name, remover.calls)
        assert output.mode == "RGBA", name
        if not expected:
            assert output.getchannel("A").getextrema() == source.getchannel("A").getextrema()
        print(f"PASS {name}")
    print(f"PASS: {len(cases)} regression cases")


if __name__ == "__main__":
    run()
