"""Execute the guest graphics setup and the actual CEF preload without requiring a GPU."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
SESSION = ROOT / 'tools/linuxfs/overlay/usr/local/bin/bannerlator-session'
PRELOAD = ROOT / 'tools/linuxfs/preload/steamwebhelper_gl.c'


class MaliSessionTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.work = Path(self.temp.name)
        panvk = self.work / 'panvk'
        panvk.mkdir()
        for name in ('panfrost_icd.json', 'libvulkan_panfrost.so'):
            (panvk / name).touch()
        probe = self.work / 'vulkaninfo'
        probe.write_text('#!/bin/sh\necho probe >> "$PROBE_LOG"\nexit "${PROBE_RC:-0}"\n')
        probe.chmod(0o755)
        self.env = {
            'PATH': f'{self.work}:{os.defpath}', 'PROBE_LOG': str(self.work / 'probes'),
            'BL_MALI_ANDROID_VULKAN': '1', 'BL_MALI_PANVK': '1',
            'PANVK_KBASE_FD_SOCKET': 'test-broker',
        }
        source = SESSION.read_text()
        start = source.index('if [ "${BL_MALI_ANDROID_VULKAN:-0}" = 1 ]; then')
        end = source.index('elif [ -n "${BL_VK_DRIVER:-}" ]; then', start)
        self.graphics = source[start:end] + '\nfi\n'
        self.graphics = self.graphics.replace('/usr/local/lib/droiddeck-mali', str(self.work))

    def run_graphics(self, **env):
        return subprocess.run(['bash', '-uc', 'step() { :; };\n' + self.graphics + '\necho READY'],
                              env=self.env | env, text=True, capture_output=True, timeout=5)

    def test_probe_only_before_gamescope(self):
        for extra in ({}, {'BL_INSIDE': '1'}):
            result = self.run_graphics(**extra)
            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
            self.assertIn('READY', result.stdout)
        self.assertEqual((self.work / 'probes').read_text(), 'probe\n')

    def test_failed_probe_does_not_start_a_different_driver(self):
        result = self.run_graphics(PROBE_RC='9')
        self.assertEqual(result.returncode, 78, result.stderr + result.stdout)
        self.assertNotIn('READY', result.stdout)
        self.assertIn('PanVK Vulkan probe failed rc=9', result.stdout)

    def test_missing_panvk_or_broker_stops_before_launch(self):
        result = self.run_graphics(PANVK_KBASE_FD_SOCKET='')
        self.assertEqual(result.returncode, 78)
        (self.work / 'panvk/libvulkan_panfrost.so').unlink()
        result = self.run_graphics()
        self.assertEqual(result.returncode, 78)
        self.assertFalse((self.work / 'probes').exists())

    def test_composition_is_mali_only_with_diagnostic_opt_out(self):
        source = SESSION.read_text()
        start = source.index('  args=(--backend wayland')
        end = source.index('  # -r is what gamescope', start)
        script = 'width=1564; height=720; nested=1564;\n' + source[start:end]
        script += '\nprintf "ARG:%s\\n" "${args[@]}"\n'
        for extra, expected in (({}, True), ({'BL_MALI_FORCE_COMPOSITION': '0'}, False),
                                ({'BL_MALI_ANDROID_VULKAN': '0'}, False)):
            result = subprocess.run(['bash', '-uc', script], env=self.env | extra,
                                    text=True, capture_output=True, check=True)
            args = [line[4:] for line in result.stdout.splitlines() if line.startswith('ARG:')]
            self.assertEqual('--force-composition' in args, expected)
            self.assertEqual(args[:3], ['--backend', 'wayland', '--expose-wayland'])


class WebhelperIsolationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not shutil.which('cc'):
            raise unittest.SkipTest('host C compiler unavailable')
        cls.temp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.temp.cleanup)
        cls.work = Path(cls.temp.name)
        cls.lib = cls.work / 'isolation.so'
        subprocess.run(['cc', '-shared', '-fPIC', str(PRELOAD), '-o', str(cls.lib)], check=True)
        fixture = cls.work / 'main.c'
        fixture.write_text(r'''
#include <stdio.h>
#include <stdlib.h>
int main(int argc, char **argv) {
  for (int i = 1; i < argc; i++) printf("arg:%s\n", argv[i]);
  const char *keys[] = {"VK_DRIVER_FILES", "GALLIUM_DRIVER", "ENABLE_GAMESCOPE_WSI",
    "DISABLE_GAMESCOPE_WSI", "LIBGL_ALWAYS_SOFTWARE", "mesa_glthread", NULL};
  for (int i = 0; keys[i]; i++) {
    const char *value = getenv(keys[i]);
    printf("env:%s=%s\n", keys[i], value ? value : "unset");
  }
  return 0;
}
''')
        cls.helper = cls.work / 'steamwebhelper'
        subprocess.run(['cc', str(fixture), '-o', str(cls.helper)], check=True)
        cls.game = cls.work / 'PPSSPPSDL'
        shutil.copyfile(cls.helper, cls.game)
        cls.game.chmod(0o755)

    def run_binary(self, binary, mali='1'):
        args = ['--disable-features=SpareRendererForSitePerProcess,WebUsbDeviceDetection',
                '--enable-features=PlatformHEVCDecoderSupport,V4L2VideoDecode', '-uimode=4']
        env = {'PATH': os.defpath, 'LD_PRELOAD': str(self.lib), 'BL_MALI_ANDROID_VULKAN': mali,
               'BL_STEAM_CEF_ISOLATED': '1', 'VK_DRIVER_FILES': '/test/panvk.json',
               'GALLIUM_DRIVER': 'zink', 'ENABLE_GAMESCOPE_WSI': '1'}
        result = subprocess.run([str(binary), *args], env=env, text=True,
                                capture_output=True, timeout=5, check=True)
        return args, result

    def test_real_reexec_preserves_valve_features_and_isolates_cef(self):
        original, result = self.run_binary(self.helper)
        argv = [line[4:] for line in result.stdout.splitlines() if line.startswith('arg:')]
        self.assertEqual(argv[:len(original)], original)
        self.assertEqual([x for x in argv if x.startswith('--disable-features=')], [original[0]])
        self.assertIn('--ozone-platform=x11', argv)
        self.assertIn('--use-angle=gl', argv)
        self.assertNotIn('--disable-gpu-rasterization', argv)
        self.assertEqual(result.stderr.count('re-exec steamwebhelper'), 1)
        for pair in ('VK_DRIVER_FILES=unset', 'GALLIUM_DRIVER=llvmpipe', 'ENABLE_GAMESCOPE_WSI=unset',
                     'DISABLE_GAMESCOPE_WSI=1', 'LIBGL_ALWAYS_SOFTWARE=1', 'mesa_glthread=false'):
            self.assertIn('env:' + pair, result.stdout)

    def test_games_and_adreno_keep_their_original_driver(self):
        for binary, mali in ((self.game, '1'), (self.helper, '0')):
            original, result = self.run_binary(binary, mali)
            argv = [line[4:] for line in result.stdout.splitlines() if line.startswith('arg:')]
            self.assertEqual(argv, original)
            self.assertIn('env:VK_DRIVER_FILES=/test/panvk.json', result.stdout)
            self.assertIn('env:GALLIUM_DRIVER=zink', result.stdout)
            self.assertIn('env:ENABLE_GAMESCOPE_WSI=1', result.stdout)


if __name__ == '__main__':
    unittest.main()
