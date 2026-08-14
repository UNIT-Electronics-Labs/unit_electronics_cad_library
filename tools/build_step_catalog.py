#!/usr/bin/env python3
"""Build a machine-readable component manifest and high-quality GLB assets.

Source CAD files are never changed.  The manifest links directly to each
versioned source; STEP files are tessellated to GLB and KiCad symbols and
footprints are rendered to SVG previews for web clients.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote


STEP_EXTENSIONS = {".step", ".stp"}
SOURCE_EXTENSIONS = {".kicad_sym", ".kicad_mod", ".lbr", ".svg", ".glb", ".f3d", ".f3z"}


def raw_url(repository: str, ref: str, relative_path: Path) -> str:
    """Create a raw GitHub URL without altering the source file or its path."""
    encoded_path = quote(relative_path.as_posix(), safe="/-_.~")
    return f"https://raw.githubusercontent.com/{repository}/{ref}/{encoded_path}"


def normalised_name(path: Path) -> str:
    """Make supplier naming variants comparable (MODULE_X, module-x, etc.)."""
    return "".join(character for character in path.stem.upper() if character.isalnum()).removeprefix("MODULE")


def associated_assets(step: Path, assets: list[Path], source_root: Path) -> list[Path]:
    """Associate matching names first; otherwise use the closest source folder."""
    named = [asset for asset in assets if normalised_name(asset) == normalised_name(step)]
    if named:
        return named

    def shared_depth(asset: Path) -> int:
        common = Path(os.path.commonpath((step.parent, asset.parent)))
        try:
            return len(common.relative_to(source_root).parts)
        except ValueError:
            return 0

    best = max((shared_depth(asset) for asset in assets), default=0)
    return [asset for asset in assets if best and shared_depth(asset) == best]


def run_kicad(command: list[str]) -> Path:
    """Run KiCad's SVG exporter and return its generated SVG file."""
    if not shutil.which("kicad-cli"):
        raise RuntimeError("kicad-cli no está instalado")
    result = subprocess.run(command, text=True, capture_output=True)
    if result.returncode:
        message = result.stderr.strip() or result.stdout.strip() or "KiCad no pudo crear el SVG"
        raise RuntimeError(message)
    output = Path(command[command.index("--output") + 1])
    svg_files = sorted(output.rglob("*.svg"))
    if not svg_files:
        raise RuntimeError("KiCad terminó sin generar un SVG")
    return svg_files[0]


def render_symbol_svg(source: Path, target: Path) -> None:
    """Generate an SVG alongside the original .kicad_sym, without modifying it."""
    with tempfile.TemporaryDirectory(prefix="symbol-svg-") as temporary:
        generated = Path(temporary) / "generated"
        generated.mkdir()
        svg = run_kicad(["kicad-cli", "sym", "export", "svg", "--output", str(generated), str(source)])
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(svg, target)


def render_footprint_svg(source: Path, target: Path) -> None:
    """Generate an SVG alongside the original .kicad_mod, without modifying it."""
    with tempfile.TemporaryDirectory(prefix="footprint-svg-") as temporary:
        library = Path(temporary) / "component.pretty"
        generated = Path(temporary) / "generated"
        library.mkdir()
        generated.mkdir()
        shutil.copy2(source, library / source.name)
        svg = run_kicad(["kicad-cli", "fp", "export", "svg", "--output", str(generated), str(library)])
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(svg, target)


def convert_to_glb(source: Path, target: Path, linear_tolerance: float, angular_tolerance: float) -> None:
    """Tessellate a coloured STEP assembly into GLB at the requested quality."""
    import cadquery as cq
    import trimesh
    from OCP.Quantity import Quantity_Color, Quantity_TOC_RGB
    from OCP.STEPCAFControl import STEPCAFControl_Reader
    from OCP.TCollection import TCollection_ExtendedString
    from OCP.TDF import TDF_LabelSequence
    from OCP.TDocStd import TDocStd_Document
    from OCP.TopAbs import TopAbs_SOLID
    from OCP.TopExp import TopExp_Explorer
    from OCP.XCAFDoc import XCAFDoc_ColorType, XCAFDoc_DocumentTool, XCAFDoc_ShapeTool

    document = TDocStd_Document(TCollection_ExtendedString("component-assets"))
    reader = STEPCAFControl_Reader()
    reader.SetColorMode(True)
    if not reader.ReadFile(str(source)) or not reader.Transfer(document):
        raise ValueError("OpenCascade no pudo leer el STEP")

    shape_tool = XCAFDoc_DocumentTool.ShapeTool_s(document.Main())
    colour_tool = XCAFDoc_DocumentTool.ColorTool_s(document.Main())
    labels = TDF_LabelSequence()
    shape_tool.GetFreeShapes(labels)
    scene = trimesh.Scene()

    with tempfile.TemporaryDirectory(prefix="component-assets-") as temporary:
        part_number = 0
        for label_index in range(1, labels.Length() + 1):
            root = XCAFDoc_ShapeTool.GetShape_s(labels.Value(label_index))
            solids = TopExp_Explorer(root, TopAbs_SOLID)
            while solids.More():
                solid = solids.Current()
                stl = Path(temporary) / f"part-{part_number}.stl"
                cq.exporters.export(
                    cq.Shape.cast(solid),
                    str(stl),
                    tolerance=linear_tolerance,
                    angularTolerance=angular_tolerance,
                )
                mesh = trimesh.load_mesh(stl, force="mesh")
                if not mesh.is_empty:
                    colour = Quantity_Color()
                    has_colour = colour_tool.GetColor(solid, XCAFDoc_ColorType.XCAFDoc_ColorSurf, colour)
                    rgb = colour.Values(Quantity_TOC_RGB) if has_colour else (0.70, 0.72, 0.78)
                    rgba = [round(max(0, min(1, channel)) * 255) for channel in rgb] + [255]
                    mesh.visual.vertex_colors = [rgba] * len(mesh.vertices)
                    scene.add_geometry(mesh, geom_name=f"part-{part_number}")
                part_number += 1
                solids.Next()

    if not scene.geometry:
        raise ValueError("el archivo STEP no produjo sólidos convertibles")
    target.parent.mkdir(parents=True, exist_ok=True)
    scene.export(target, file_type="glb")


def asset_link(path: Path, source_root: Path, repository: str, source_ref: str) -> dict[str, str]:
    relative = path.relative_to(source_root)
    return {"path": relative.as_posix(), "url": raw_url(repository, source_ref, relative)}


def render_link(
    kind: str,
    source: Path,
    source_root: Path,
    output: Path,
    repository: str,
    source_ref: str,
    assets_ref: str,
) -> dict[str, str]:
    """Create an SVG asset and return both the original-file and SVG URLs."""
    relative = source.relative_to(source_root)
    identifier = hashlib.sha256(relative.as_posix().encode()).hexdigest()[:12]
    render_path = Path("svg") / kind / f"{source.stem}-{identifier}.svg"
    asset = asset_link(source, source_root, repository, source_ref)
    try:
        if kind == "symbols":
            render_symbol_svg(source, output / render_path)
        else:
            render_footprint_svg(source, output / render_path)
        asset["svg_url"] = raw_url(repository, assets_ref, render_path)
        asset["svg_path"] = render_path.as_posix()
        print(f"SVG generado: {relative}")
    except Exception as error:
        asset["svg_error"] = str(error)
        print(f"No se pudo generar SVG para {relative}: {error}", file=sys.stderr)
    return asset


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=Path("."), help="directorio de los componentes")
    parser.add_argument("--output", type=Path, default=Path("assets"), help="salida: catalog.json y modelos GLB")
    parser.add_argument("--repository", default=os.environ.get("GITHUB_REPOSITORY", ""), help="owner/repository de GitHub")
    parser.add_argument("--source-ref", default=os.environ.get("GITHUB_SHA", "main"), help="commit/ref de los archivos fuente")
    parser.add_argument("--assets-ref", default="assets", help="rama que alojará catalog.json y los GLB")
    parser.add_argument("--linear-tolerance", type=float, default=0.025, help="tolerancia lineal en mm (por defecto: 0.025)")
    parser.add_argument("--angular-tolerance", type=float, default=0.025, help="tolerancia angular en radianes (por defecto: 0.025)")
    arguments = parser.parse_args()

    if not arguments.repository:
        parser.error("--repository es obligatorio fuera de GitHub Actions")
    if arguments.linear_tolerance <= 0 or arguments.angular_tolerance <= 0:
        parser.error("las tolerancias deben ser mayores que cero")

    source_root = arguments.input.resolve()
    output = arguments.output.resolve()
    if output == source_root:
        parser.error("--output debe ser un subdirectorio distinto de --input")
    if output.exists():
        shutil.rmtree(output)
    output.mkdir(parents=True)

    source_files: dict[str, list[Path]] = {extension: [] for extension in SOURCE_EXTENSIONS}
    step_files: list[Path] = []
    for path in sorted(source_root.rglob("*")):
        if not path.is_file() or output in path.parents:
            continue
        extension = path.suffix.lower()
        if extension in STEP_EXTENSIONS:
            step_files.append(path)
        elif extension in source_files:
            source_files[extension].append(path)

    symbol_assets = {
        asset: render_link(
            "symbols", asset, source_root, output, arguments.repository,
            arguments.source_ref, arguments.assets_ref,
        )
        for asset in source_files[".kicad_sym"]
    }
    footprint_assets = {
        asset: render_link(
            "footprints", asset, source_root, output, arguments.repository,
            arguments.source_ref, arguments.assets_ref,
        )
        for asset in source_files[".kicad_mod"]
    }

    components: list[dict[str, object]] = []
    for step in step_files:
        relative = step.relative_to(source_root)
        identifier = hashlib.sha256(relative.as_posix().encode()).hexdigest()[:12]
        model_path = Path("models") / f"{step.stem}-{identifier}.glb"
        component: dict[str, object] = {
            "id": identifier,
            "source_step": asset_link(step, source_root, arguments.repository, arguments.source_ref),
            "symbols": [symbol_assets[asset]
                        for asset in associated_assets(step, source_files[".kicad_sym"], source_root)],
            "footprints": [footprint_assets[asset]
                           for asset in associated_assets(step, source_files[".kicad_mod"], source_root)],
            "eagle_libraries": [asset_link(asset, source_root, arguments.repository, arguments.source_ref)
                                for asset in associated_assets(step, source_files[".lbr"], source_root)],
            "svg": [asset_link(asset, source_root, arguments.repository, arguments.source_ref)
                    for asset in associated_assets(step, source_files[".svg"], source_root)],
        }
        try:
            convert_to_glb(step, output / model_path, arguments.linear_tolerance, arguments.angular_tolerance)
            component["model_glb"] = {
                "path": model_path.as_posix(),
                "url": raw_url(arguments.repository, arguments.assets_ref, model_path),
                "linear_tolerance_mm": arguments.linear_tolerance,
                "angular_tolerance_rad": arguments.angular_tolerance,
            }
            print(f"GLB generado: {relative}")
        except Exception as error:
            component["model_error"] = str(error)
            print(f"No se pudo convertir {relative}: {error}", file=sys.stderr)
        components.append(component)

    manifest = {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "repository": arguments.repository,
        "source_ref": arguments.source_ref,
        "assets_ref": arguments.assets_ref,
        "catalog_url": raw_url(arguments.repository, arguments.assets_ref, Path("catalog.json")),
        "components": components,
        "unassociated": {
            "eagle_libraries": [asset_link(asset, source_root, arguments.repository, arguments.source_ref)
                                for asset in source_files[".lbr"]],
            "svg": [asset_link(asset, source_root, arguments.repository, arguments.source_ref)
                    for asset in source_files[".svg"]],
        },
    }
    (output / "catalog.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Manifest creado en {output / 'catalog.json'} ({len(components)} componente(s))")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
