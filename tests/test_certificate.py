import importlib.util
import unittest
import os
from pathlib import Path
import subprocess
import tempfile

root=Path(__file__).resolve().parents[1]
script=root/'skills/instabox-handoff/scripts/renew_ssh.py'
spec=importlib.util.spec_from_file_location('renew',script)
module=importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
class CertificateTests(unittest.TestCase):
    def test_renew_and_skip(self):
        with tempfile.TemporaryDirectory(prefix='cert-test-') as directory:
            base=Path(directory)
            def run(argv):
                subprocess.run([str(x) for x in argv],check=True,capture_output=True)
            for name in ('ca','client'):
                run(['ssh-keygen','-q','-t','ed25519','-N','','-f',base/name])
            run(['ssh-keygen','-q','-s',base/'ca','-I','test','-V','-1m:+2m',base/'client.pub'])
            cert=base/'client-cert.pub'
            assert not module.is_current(cert)
            cli=base/'instabox-test'
            marker=base/'renewed'
            cli.write_text('#!/usr/bin/env python3\nimport subprocess\nfrom pathlib import Path\n'+
                'subprocess.run('+repr(['ssh-keygen','-q','-s',str(base/'ca'),'-I','renewed','-V','-1m:+1h',str(base/'client.pub')])+',check=True)\n'+
                'Path('+repr(str(marker))+').write_text("renewed")\n')
            cli.chmod(0o700)
            args=['python3',script,'--machine','test','--cert',cert,'--cli',cli]
            run(args)
            assert marker.exists() and module.is_current(cert)
            marker.unlink()
            run(args)
            assert not marker.exists(), 'Fresh certificate must not renew every SSH connection'
            print('Certificate near-expiry renewal and fresh-certificate skip: passed')
