import json,sqlite3,tempfile
from pathlib import Path
from astra_blocks.store import BlockStore

def import_blocks(source_path,memory,limit=None,hook=None):
    """Read-only source connection, consistent SQLite backup into disposable copy."""
    source_path=Path(source_path).resolve()
    if source_path==memory.path.resolve():raise ValueError('source_destination_must_differ')
    with tempfile.TemporaryDirectory(prefix='memory-source-snapshot-') as tmp:
        snapshot=Path(tmp)/'snapshot.sqlite'
        source=sqlite3.connect(source_path.as_uri()+'?mode=ro',uri=True)
        target=sqlite3.connect(snapshot)
        try:source.backup(target)
        finally:target.close();source.close()
        blocks=BlockStore(snapshot)
        try:
            audit=blocks.audit()
            if not audit['healthy']:raise ValueError('source_blocks_unhealthy')
            pubs=list(blocks.db.execute('SELECT * FROM publications ORDER BY slot'))
            if limit is not None:
                if type(limit)!=int or limit<0:raise ValueError('invalid_limit')
                pubs=pubs[:limit]
            for pub in pubs:
                evidence=blocks.db.execute('SELECT a.raw,s.context FROM attempts a JOIN sessions s ON s.id=a.session_id WHERE a.id=?',(pub['attempt_id'],)).fetchone()
                doc=json.loads(pub['document']);key='solana-devnet:'+str(pub['slot'])+':'+doc['block']['blockhash']
                ident=memory.capture(key,pub['slot'],bytes(evidence['raw']),json.loads(evidence['context']))
                if hook:hook('captured',ident)
                memory.publish(ident)
                if hook:hook('published',ident)
            return memory.audit()
        finally:blocks.close()
