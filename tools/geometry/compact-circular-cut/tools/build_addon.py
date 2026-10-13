from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED
root=Path(__file__).resolve().parents[1]
target=root/'dist/compact_circular_cut_v1.1.1.zip'
target.parent.mkdir(exist_ok=True)
with ZipFile(target,'w',compression=ZIP_DEFLATED) as archive:
    for name in ('__init__.py','core.py','README_RU.txt'):
        archive.write(root/'src/compact_circular_cut'/name,'compact_circular_cut/'+name)
print(target)
