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
        built = subprocess.run(cmd, capture_output=True, text=True)
        self.assertEqual(0, built.returncode, built.stdout + built.stderr)
        ran = subprocess.run([str(binary)], cwd=self.work, capture_output=True, text=True)
        self.assertEqual(0, ran.returncode, ran.stdout + ran.stderr)

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

    def test_toplevel_reopens_after_null_attach(self):
        source = (BACKEND / 'src/compositor.c').read_text()
        start = source.index('enum surface_role {')
        end = source.index('\nstatic struct wl_list g_surfaces', start)
        (self.work / 'compositor_surface_types.c').write_text(source[start:end])

        def function(signature):
            start = source.index(signature)
            return source[start:source.index('\n}', start) + 2]

        signatures = [
            'static void send_toplevel_configure(struct surface *s) {',
            'static void xdg_toplevel_set_fullscreen(',
            'static void xdg_toplevel_unset_fullscreen(',
            'static void surface_attach(',
            'static void surface_commit(',
        ]
        (self.work / 'compositor_remap_under_test.c').write_text(
            '\n\n'.join(function(signature) for signature in signatures))
        self.run_fixture('toplevel_remap_test.c', (BACKEND / 'prebuilt/include', BACKEND / 'generated'))


if __name__ == '__main__':
    unittest.main()
