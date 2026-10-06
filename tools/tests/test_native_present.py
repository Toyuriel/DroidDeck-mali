"""Host regressions for the production compositor code, using mocked GPU/display calls."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
NATIVE = ROOT / 'tools/tests/native'
BACKEND = ROOT / 'app/src/main/cpp/waylandcomp'


class NativePresentTest(unittest.TestCase):
    def setUp(self):
        if not shutil.which('cc'):
            self.skipTest('host C compiler unavailable')
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.work = Path(self.temp.name)

    def run_fixture(self, name, includes=()):
        binary = self.work / 'test'
        cmd = ['cc', '-std=c11', '-Werror=implicit-function-declaration', '-ffunction-sections',
               '-fdata-sections', '-Wl,--gc-sections', '-pthread', '-I', str(self.work)]
        for path in includes:
            cmd += ['-I', str(path)]
        cmd += [str(NATIVE / name), '-o', str(binary)]
        subprocess.run(cmd, check=True, capture_output=True, text=True)
        subprocess.run([str(binary)], cwd=self.work, check=True, capture_output=True, text=True)

    def test_delayed_present_and_foreign_image_ownership(self):
        candidates = [Path(os.environ.get('DROIDDECK_VULKAN_HEADERS', '/usr/include')), Path('/usr/local/include')]
        for var in ('ANDROID_NDK_LATEST_HOME', 'ANDROID_NDK_HOME', 'ANDROID_NDK_ROOT'):
            if os.environ.get(var):
                candidates.append(Path(os.environ[var]) / 'toolchains/llvm/prebuilt/linux-x86_64/sysroot/usr/include')
        headers = next((p for p in candidates if (p / 'vulkan/vulkan.h').is_file()), None)
        if headers is None:
            self.skipTest('Vulkan headers unavailable; set DROIDDECK_VULKAN_HEADERS or an Android NDK path')
        # Isolate Vulkan headers from the NDK's Bionic libc headers when compiling with a host cc.
        include = self.work / 'include'
        include.mkdir()
        for name in ('vulkan', 'vk_video'):
            if (headers / name).is_dir():
                (include / name).symlink_to(headers / name, target_is_directory=True)
        self.run_fixture('vk_present_sync_test.c', (NATIVE / 'include', include, BACKEND / 'prebuilt/include'))

    def test_compositor_log_follows_session(self):
        source = (BACKEND / 'src/compositor.c').read_text()
        start = source.index('#define SESSION_LOG_DIR')
        end = source.index('/* At most ~10 lines a second', start)
        (self.work / 'compositor_log_under_test.c').write_text(source[start:end])
        self.run_fixture('log_rotation_test.c')


if __name__ == '__main__':
    unittest.main()
