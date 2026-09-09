import concurrent.futures
from pathlib import Path
import re
import subprocess
import sys
import unittest

sys.path.insert(0, str(Path.cwd()))
prefix = sys.argv[1]
directory = Path(prefix + "-modules")
directory.mkdir(exist_ok=True)
suite = unittest.defaultTestLoader.discover("tests")
def flatten(value):
    for test in value:
        if isinstance(test, unittest.TestSuite):
            yield from flatten(test)
        else:
            yield test
tests = list(flatten(suite))
modules = sorted({"tests." + type(test).__module__.split(".")[-1] for test in tests})
print("DISCOVER", len(modules), len(tests), flush=True)
def run(module):
    log = directory / (module + ".log")
    with log.open("w") as stream:
        process = subprocess.run([sys.executable, "-m", "unittest", "-v", module], stdout=stream, stderr=subprocess.STDOUT, timeout=1800)
    output = log.read_text()
    match = re.search(r"Ran (\d+) tests?", output)
    return module, process.returncode, int(match.group(1)) if match else 0
results = []
with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
    for future in concurrent.futures.as_completed([pool.submit(run, module) for module in modules]):
        item = future.result()
        results.append(item)
        print("PASS_MODULE" if not item[1] else "FAIL_MODULE", item[0], item[2], flush=True)
assert len(results) == len(modules) and sum(item[2] for item in results) == len(tests), results
assert not any(item[1] for item in results), [item for item in results if item[1]]
print("GLOBAL_OK", len(modules), len(tests), flush=True)
