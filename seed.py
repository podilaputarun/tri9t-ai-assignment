from pathlib import Path
from app import import_pdf
HERE=Path(__file__).resolve().parent
# Copy the two assignment PDFs into this folder, or pass their absolute paths as arguments.
import sys
v1=Path(sys.argv[1]).resolve() if len(sys.argv)>1 else HERE/'ct200_manual.pdf'
v2=Path(sys.argv[2]).resolve() if len(sys.argv)>2 else HERE/'ct200_manual_v2.pdf'
if not v1.exists() or not v2.exists():
    raise SystemExit('PDFs not found. Run: python seed.py /path/to/ct200_manual.pdf /path/to/ct200_manual_v2.pdf')
print('Imported', import_pdf(str(v1),'v1'), 'as v1')
print('Imported', import_pdf(str(v2),'v2'), 'as v2')
