"""Chemistry / cheminformatics file-format sidecar.

Covers the molecular file formats used in computational chemistry,
cheminformatics, and structural biology.

Inputs / outputs:
  * SMILES (.smi)        Simplified Molecular Input Line Entry
  * InChI / InChI Key
  * MOL / SDF (.mol/.sdf)  MDL Molfile / SDF
  * MOL2 (.mol2)         Tripos
  * PDB (.pdb)           Protein Data Bank
  * XYZ (.xyz)           Cartesian coordinates
  * CIF (.cif)           Crystallographic Information File
  * MOL3 / V3000

Backed by RDKit (BSD-3) for cheminformatics + Open Babel (GPL-2 / OBabel CLI)
for the broader format pool.

Operations:
  convert    Read any supported format, write any other.
  info       Probe formula / MW / heavy-atom count / SMILES / InChI.
  fingerprint Generate Morgan / RDKit / MACCS / Avalon fingerprints.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "_lib"))
from ucx_sidecar import emit




def fail(code: str, message: str) -> int:
    emit("error", code=code, message=message)
    return 1


# Open Babel CLI fallback for formats RDKit doesn't read.
def _find_obabel() -> str | None:
    env = os.environ.get("OBABEL_PATH")
    if env and Path(env).is_file(): return env
    return shutil.which("obabel") or shutil.which("obabel.exe")


def _read_rdkit(path: Path):
    from rdkit import Chem
    ext = path.suffix.lower()
    if ext == ".smi":
        with path.open() as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"): continue
                smi = line.split()[0]
                yield Chem.MolFromSmiles(smi)
    elif ext == ".sdf":
        for mol in Chem.SDMolSupplier(str(path)):
            if mol is not None: yield mol
    elif ext == ".mol":
        m = Chem.MolFromMolFile(str(path))
        if m is not None: yield m
    elif ext == ".mol2":
        m = Chem.MolFromMol2File(str(path))
        if m is not None: yield m
    elif ext == ".pdb":
        m = Chem.MolFromPDBFile(str(path), removeHs=False)
        if m is not None: yield m
    elif ext == ".xyz":
        from rdkit.Chem import rdDetermineBonds
        m = Chem.MolFromXYZFile(str(path))
        if m is not None:
            try: rdDetermineBonds.DetermineBonds(m)
            except Exception: pass
            yield m
    else:
        raise ValueError(f"RDKit can't read {ext}; try Open Babel (--backend obabel).")


def _write_rdkit(mols, path: Path) -> None:
    from rdkit import Chem
    ext = path.suffix.lower()
    if ext == ".smi":
        with path.open("w") as f:
            for m in mols:
                if m is None: continue
                f.write(Chem.MolToSmiles(m) + "\n")
    elif ext == ".sdf":
        w = Chem.SDWriter(str(path))
        for m in mols:
            if m is not None: w.write(m)
        w.close()
    elif ext == ".mol":
        for m in mols:
            if m is None: continue
            Chem.MolToMolFile(m, str(path)); break
    elif ext == ".pdb":
        for m in mols:
            if m is None: continue
            Chem.MolToPDBFile(m, str(path)); break
    elif ext == ".xyz":
        for m in mols:
            if m is None: continue
            path.write_text(Chem.MolToXYZBlock(m), encoding="utf-8"); break
    elif ext == ".inchi":
        with path.open("w") as f:
            for m in mols:
                if m is None: continue
                f.write(Chem.MolToInchi(m) + "\n")
    else:
        raise ValueError(f"RDKit can't write {ext}; try Open Babel (--backend obabel).")


def _convert_obabel(src: Path, out_path: Path) -> int:
    obabel = _find_obabel()
    if not obabel:
        return fail("missing_obabel",
                    "Open Babel CLI not found. Install via http://openbabel.org or `choco install openbabel`.")
    proc = subprocess.run([obabel, str(src), "-O", str(out_path)],
                          capture_output=True, text=True)
    if proc.returncode != 0:
        tail = (proc.stderr or proc.stdout).strip().splitlines()[-3:]
        for ln in tail: emit("log", level="error", message=ln)
        return fail("obabel_failed", f"{src.name}: rc={proc.returncode}")
    return 0


def op_convert(args: argparse.Namespace) -> int:
    inputs = [Path(p) for p in args.input]
    miss = [str(p) for p in inputs if not p.is_file()]
    if miss: return fail("missing_input", f"Molecule file(s) not found: {miss}")
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    target_ext = "." + args.format.lstrip(".").lower()

    total = len(inputs)
    started = time.monotonic()
    emit("progress", percent=0, stage="chem", eta_seconds=None)

    backend = args.backend.lower()
    for i, src in enumerate(inputs):
        out_path = out_dir / (src.stem + target_ext)
        try:
            if backend == "obabel":
                rc = _convert_obabel(src, out_path)
                if rc != 0: return rc
            else:
                mols = list(_read_rdkit(src))
                _write_rdkit(mols, out_path)
        except ImportError as ex:
            return fail("missing_dep", str(ex))
        except Exception as ex:
            emit("log", level="warn", message=f"{src.name}: {ex} -- retrying with Open Babel")
            rc = _convert_obabel(src, out_path)
            if rc != 0: return rc

        emit("molecule",
             input=str(src), output=str(out_path),
             size_bytes=out_path.stat().st_size,
             format=target_ext.lstrip("."), backend=backend)
        pct = (i + 1) / total * 100
        elapsed = time.monotonic() - started
        eta = (elapsed / (pct / 100) - elapsed) if pct > 1 else None
        emit("progress", percent=round(pct, 1),
             stage=f"{i+1}/{total}",
             eta_seconds=int(eta) if eta and eta < 86400 else None)

    emit("complete", output=str(out_dir), size_bytes=0, count=total)
    return 0


def op_info(args: argparse.Namespace) -> int:
    src = Path(args.input)
    if not src.is_file(): return fail("missing_input", f"File not found: {src}")
    try:
        from rdkit import Chem
        from rdkit.Chem import Descriptors
    except ImportError as ex:
        return fail("missing_rdkit", str(ex))
    try:
        mol = next(iter(_read_rdkit(src)))
    except StopIteration:
        return fail("read_failed", f"{src.name}: no parseable molecule.")
    if mol is None:
        return fail("read_failed", f"{src.name}: failed to parse.")
    emit("molecule_info",
         path=str(src),
         smiles=Chem.MolToSmiles(mol),
         inchi=Chem.MolToInchi(mol),
         inchi_key=Chem.InchiToInchiKey(Chem.MolToInchi(mol)),
         formula=Chem.rdMolDescriptors.CalcMolFormula(mol),
         mw=float(Descriptors.MolWt(mol)),
         heavy_atom_count=int(mol.GetNumHeavyAtoms()),
         ring_count=int(mol.GetRingInfo().NumRings()))
    emit("complete", output=str(src), size_bytes=src.stat().st_size, count=1)
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="chemkit-sidecar",
                                description="Chemistry molecular format conversion.")
    sub = p.add_subparsers(dest="op", required=True)
    c = sub.add_parser("convert", help="Convert SMILES/MOL/SDF/MOL2/PDB/XYZ/CIF/InChI.")
    c.add_argument("--input", nargs="+", required=True)
    c.add_argument("--output-dir", required=True, dest="output_dir")
    c.add_argument("--format", required=True,
                   help="smi | sdf | mol | mol2 | pdb | xyz | cif | inchi")
    c.add_argument("--backend", default="rdkit", choices=["rdkit", "obabel"],
                   help="Use rdkit (default) or shell out to Open Babel.")
    i = sub.add_parser("info", help="Probe molecular formula / MW / SMILES / InChI.")
    i.add_argument("--input", required=True)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.op == "convert": return op_convert(args)
        if args.op == "info":    return op_info(args)
        return fail("unknown_op", f"Unknown op: {args.op}")
    except KeyboardInterrupt:
        return fail("cancelled", "Cancelled by user.")
    except Exception as ex:
        return fail("internal", f"{type(ex).__name__}: {ex}")


if __name__ == "__main__":
    raise SystemExit(main())
