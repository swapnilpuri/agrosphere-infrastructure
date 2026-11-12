"""Request normal stop of one live owned POC-CLOSE fixture."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import tempfile

from poc_close_owner import ROOT, process_identity


def request_stop(manifest):
    path = Path(manifest).resolve(strict=True)
    owner = json.loads(path.read_text())
    run = owner['runId']
    assert len(run) == 32 and all(character in '0123456789abcdef' for character in run)
    assert path == ROOT / 'target/poc-close' / run / 'owner.json'
    assert owner['project'] == 'agrosphere-poc-close-' + run
    operator = owner['operatorProcess']
    assert process_identity(operator['pid']) == operator['started'], 'Use exact recovery after the operator exits'
    private = Path(owner['privateDirectory']).resolve(strict=True)
    assert private.parent == Path(tempfile.gettempdir()).resolve()
    assert private.name.startswith(owner['project'] + '-')
    assert not private.is_symlink() and not private.is_junction()
    assert (private / '.poc-close-owner').read_text() == run
    target = private / 'stop'
    assert str(target) == owner['stopFile']
    assert not target.is_symlink() and not target.is_junction()
    target.write_text('Normal stop requested ' + datetime.now(timezone.utc).isoformat())
    print('Stop requested. Current admitted captures finish before the native hold exits and cleanup runs.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('manifest')
    request_stop(parser.parse_args().manifest)
