import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


def probe(executable, codepage, destination, redirected, shell):
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    kernel.CreateFileW.restype = wintypes.HANDLE
    kernel.ReadConsoleOutputCharacterW.argtypes = [wintypes.HANDLE, wintypes.LPWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD)]
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    assert kernel.SetConsoleOutputCP(codepage)
    handle = kernel.CreateFileW('CONOUT$', 0xC0000000, 3, None, 3, 0, None)
    command = [executable, '--help']
    if shell != 'native':
        invocation = "& '" + executable.replace("'", "''") + "' --help"
        command = [shell + '.exe', '-NoProfile', '-Command', invocation]
    with open('CONOUT$', 'wb', buffering=0) as output, open('CONIN$', 'rb', buffering=0) as input_stream:
        result = subprocess.run(command, stdin=subprocess.DEVNULL if redirected else input_stream, stdout=output, stderr=output, timeout=30)
    buffer = ctypes.create_unicode_buffer(16000)
    count = wintypes.DWORD()
    assert kernel.ReadConsoleOutputCharacterW(handle, buffer, 16000, 0, ctypes.byref(count))
    kernel.CloseHandle(handle)
    Path(destination).write_text(json.dumps(dict(code=result.returncode, text=buffer[:count.value], codepage=kernel.GetConsoleOutputCP())), encoding='utf-8')


@unittest.skipUnless(os.name == 'nt' and os.environ.get('GAIT_EXECUTABLE'), 'requires Windows Native executable')
class WindowsConsole(unittest.TestCase):
    def test_unicode_console_and_unchanged_codepage(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'result.json'
            startup = subprocess.STARTUPINFO()
            startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            startup.wShowWindow = 0
            cases = [('native', 936, False), ('native', 65001, False), ('native', 437, True), ('powershell', 936, False), ('pwsh', 936, False)]
            for shell, codepage, redirected in cases:
                with self.subTest(shell=shell, codepage=codepage, redirected_stdin=redirected):
                    subprocess.run([sys.executable, __file__, '--probe', os.environ['GAIT_EXECUTABLE'], str(codepage), str(path), str(int(redirected)), shell], creationflags=subprocess.CREATE_NEW_CONSOLE, startupinfo=startup, check=True, timeout=45)
                    result = json.loads(path.read_text(encoding='utf-8'))
                    self.assertEqual(0, result['code'])
                    self.assertEqual(codepage, result['codepage'])
                    self.assertIn('结果：', result['text'])
                    self.assertIn('用法：gait', result['text'])


if __name__ == '__main__':
    if sys.argv[1:2] == ['--probe']:
        probe(sys.argv[2], int(sys.argv[3]), sys.argv[4], bool(int(sys.argv[5])), sys.argv[6])
    else:
        unittest.main()
