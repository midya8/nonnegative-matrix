"""Check the installed tests and full CLI outputs outside the checkout.

Use --section tests or --section commands to run either half on its own.
The default runs both. These are same-runtime packaging comparisons, not
independent numerical or statistical evidence.
"""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import venv

ROOT = Path(__file__).resolve().parents[1]
ENV = os.environ.copy()
ENV.pop('PYTHONPATH', None)
ENV.update(OPENBLAS_NUM_THREADS='1', OMP_NUM_THREADS='1')
MODULES = ['partslab', 'partslab.__main__', 'partslab.audit',
           'partslab.certificate', 'partslab.core', 'partslab.data',
           'partslab.experiment', 'partslab.face', 'partslab.face_export',
           'partslab.io']
COMMANDS = [
    ['demo'], ['train', '--out', 'models.json', '--guard', 'guard.json'],
    ['evaluate', '--models', 'models.json', '--guard', 'guard.json', '--out', 'report.json'],
    ['evaluate', '--out', 'saved-report.json'],
    ['audit', '--out', 'audit.json'],
    ['predict', '--pixels', 'pixels.json', '--out', 'predict.json'],
    ['predict', '--pixels', 'pixels.json', '--models', 'models.json', '--out', 'fresh-predict.json'],
    ['certify', '--problem', 'problem.json', '--out', 'certificate.json'],
    ['verify-certificate', '--witness', 'certificate.json'],
    ['face', '--problem', 'face-problem.json', '--out', 'face.json'],
    ['verify-face', '--witness', 'face.json'],
    ['face-export', '--out', 'face-reference.json'],
]
FILES = ['models.json', 'guard.json', 'report.json', 'saved-report.json',
         'audit.json', 'predict.json', 'fresh-predict.json', 'certificate.json',
         'face.json', 'face-reference.json']


def call(args, cwd, env=ENV):
    return subprocess.check_output(args, cwd=cwd, env=env, text=True)


parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--section', choices=['all', 'tests', 'commands'], default='all')
args = parser.parse_args()
with tempfile.TemporaryDirectory() as directory:
    work = Path(directory)
    wheels = work / 'wheels'
    wheels.mkdir()
    call([sys.executable, '-m', 'pip', 'wheel', '--no-deps', '-w', str(wheels), str(ROOT)], work)
    built = list(wheels.glob('*.whl'))
    assert len(built) == 1, built
    venv.create(work / 'env', with_pip=True)
    py = str(work / 'env/bin/python')
    call([py, '-m', 'pip', 'install', str(built[0])], work)
    outside = work / 'outside'
    outside.mkdir()
    for name in ['tests', 'examples', 'assets', 'docs']:
        shutil.copytree(ROOT / name, outside / name)
    # Two existing tests find the static browser bundle beside the package.
    # Copy that static directory only, never any library Python source.
    package = Path(call([py, '-I', '-c', 'import partslab;print(partslab.__path__[0])'], work).strip())
    shutil.copytree(ROOT / 'docs', package.parent / 'docs')
    suite = '''
import importlib,importlib.util,json,pathlib,sys,unittest
outside=pathlib.Path.cwd().resolve()
sys.path.insert(0,str(outside))
names=json.loads(sys.argv[1])
source=pathlib.Path(sys.argv[2]).resolve()
prefix=pathlib.Path(sys.prefix).resolve()
for name in names:importlib.import_module(name)
def check():
    for name in names:
        origin=pathlib.Path(importlib.util.find_spec(name).origin).resolve()
        assert origin.is_relative_to(prefix),(name,str(origin))
        assert not origin.is_relative_to(source),(name,str(origin))
        assert 'site-packages' in origin.parts,(name,str(origin))
check()
if sys.argv[3]=='tests':
    tests=unittest.defaultTestLoader.discover(str(outside/'tests'))
    result=unittest.TextTestRunner(verbosity=2).run(tests)
    assert result.testsRun>0 and result.wasSuccessful()
    print(json.dumps(dict(tests=result.testsRun)))
check()
print(json.dumps(dict(installed_origins=len(names),checked_before_and_after=True)))
'''
    if args.section in ['all', 'tests']:
        print(call([py, '-I', '-c', suite, json.dumps(MODULES), str(ROOT), 'tests'], outside))
    if args.section in ['all', 'commands']:
        print(call([py, '-I', '-c', suite, json.dumps(MODULES), str(ROOT), 'imports'], outside))
        reference = work / 'reference'
        reference.mkdir()
        fixtures = {
            'pixels.json': [0.] * 64,
            'problem.json': {'pixels': [1., 1.], 'basis': [[1., 0.], [0., 1.]], 'coefficients': [1., 0.]},
            'face-problem.json': {'pixels': [.5, .5], 'basis': [[1., 1.], [1., 0.]], 'support': [0], 'pixel': 0},
        }
        for folder in [reference, outside]:
            for name, value in fixtures.items():
                (folder / name).write_text(json.dumps(value))
        source_env = ENV.copy()
        source_env['PYTHONPATH'] = str(ROOT)
        expected = []
        for command in COMMANDS:
            output = call([sys.executable, '-m', 'partslab'] + command, reference, source_env).strip()
            expected.append(json.loads(output) if output else None)
        saved = {name: json.loads((reference / name).read_text()) for name in FILES}
        for entry in [[py, '-I', '-m', 'partslab'], [str(work / 'env/bin/partslab')]]:
            for command, report in zip(COMMANDS, expected):
                output = call(entry + command, outside).strip()
                assert (json.loads(output) if output else None) == report, (entry, command)
            for name, report in saved.items():
                assert json.loads((outside / name).read_text()) == report, (entry, name)
        print(call([py, '-I', '-c', suite, json.dumps(MODULES), str(ROOT), 'imports'], outside))
        print(json.dumps(dict(command_invocations=len(COMMANDS), command_kinds=10,
                              complete_output_files=len(FILES), fresh_models=6, entrypoints=2)))
