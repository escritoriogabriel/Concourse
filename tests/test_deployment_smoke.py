import os
import subprocess
import sys
import textwrap
import unittest


class DeploymentSmokeTests(unittest.TestCase):
    def test_vercel_runtime_imports_and_serves_home(self):
        code = textwrap.dedent(
            """
            from fastapi.testclient import TestClient
            import app

            assert app.DATA_DIR.as_posix() == '/tmp/editalos'
            client = TestClient(app.app)
            response = client.get('/')
            assert response.status_code == 200, response.text
            assert 'text/html' in response.headers['content-type']
            static = client.get('/static/app.js')
            assert static.status_code == 200
            """
        )
        env = os.environ.copy()
        env.pop('EDITALOS_DATA', None)
        env['VERCEL'] = '1'
        result = subprocess.run(
            [sys.executable, '-c', code],
            cwd=os.path.dirname(os.path.dirname(__file__)),
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)


if __name__ == '__main__':
    unittest.main()
