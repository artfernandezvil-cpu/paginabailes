"""Create a consistent private backup of the database and uploaded files."""
import argparse
import datetime
from pathlib import Path
import sqlite3
import tempfile
import zipfile
import server

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('output',nargs='?',default='respaldo-bailes-'+datetime.date.today().isoformat()+'.zip')
    args=parser.parse_args()
    output=Path(args.output).resolve()
    if output.exists():raise SystemExit('El archivo de destino ya existe. Elige otro nombre.')
    with tempfile.TemporaryDirectory() as temporary:
        snapshot=Path(temporary)/'archive.sqlite'
        with server.connect() as original,sqlite3.connect(snapshot) as saved:
            original.backup(saved)
            media_ids={r[0] for r in saved.execute('SELECT id FROM media UNION SELECT id FROM assets')}
        with zipfile.ZipFile(output,'w',zipfile.ZIP_DEFLATED) as archive:
            archive.write(snapshot,'runtime/archive.sqlite')
            for mid in media_ids:
                source=server.DATA_DIR/'media'/mid
                if source.is_file():archive.write(source,'runtime/media/'+mid)
    output.chmod(0o600)
    print('Respaldo creado:',output)
if __name__=='__main__':main()
