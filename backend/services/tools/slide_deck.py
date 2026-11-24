from __future__ import annotations

import re
from copy import deepcopy
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
from xml.etree import ElementTree as ET
from zipfile import ZIP_DEFLATED, ZipFile

from defusedxml.ElementTree import fromstring
from PIL import Image, ImageOps

from backend.services.python_runner import resolve_input_files
from backend.services.tools.artifact_workspace import ArtifactWorkspace
from backend.services.tools.tool_protocol import ModelToolResult

TEMPLATE = Path(__file__).resolve().parents[2] / "ai_engine/skills/slides/template.pptx"
NS = {
    "p": "http://schemas.openxmlformats.org/presentationml/2006/main",
    "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
    "cp": "http://schemas.openxmlformats.org/package/2006/metadata/core-properties",
    "dcterms": "http://purl.org/dc/terms/",
}
for prefix, uri in NS.items():
    ET.register_namespace(prefix, uri)
SLIDE_TYPE = "application/vnd.openxmlformats-officedocument.presentationml."


def _text(value):
    if re.search(r"[^\x09\x0a\x0d\x20-\ud7ff\ue000-\ufffd\U00010000-\U0010ffff]", value):
        raise ValueError("invalid_slide_text")
    return value


def _xml(element):
    return ET.tostring(element, encoding="utf-8", xml_declaration=True)


def _package_manifest(source):
    root = fromstring(source)
    namespace, _ = root.tag[1:].split("}", 1)
    prefix = f"{{{namespace}}}"
    for element in root.iter():
        element.tag = element.tag.removeprefix(prefix)
    root.set("xmlns", namespace)
    return root


def _content(template, fields, points=()):
    root = fromstring(template)
    for body in root.findall(".//p:txBody", NS):
        for paragraph in list(body.findall("a:p", NS)):
            node = paragraph.find(".//a:t", NS)
            if node is None:
                continue
            if node.text == "POINT":
                body.remove(paragraph)
                characters = sum(len(value) for value in points)
                for value in points:
                    line = deepcopy(paragraph)
                    line.find(".//a:t", NS).text = _text(value)
                    if characters > 340:
                        line.find(".//a:defRPr", NS).set("sz", "1550")
                    body.append(line)
            elif node.text in fields:
                node.text = _text(fields[node.text])
    return _xml(root)


def _relationships(template, targets):
    root = _package_manifest(template)
    for child in root:
        kind = child.attrib["Type"].rsplit("/", 1)[-1]
        if kind in targets:
            child.set("Target", targets[kind])
    return _xml(root)


def _image(path):
    if path is None or path.suffix.lower() not in {".jpg", ".jpeg", ".png", ".webp"}:
        raise ValueError("file_not_available")
    with Image.open(path, formats=("JPEG", "PNG", "WEBP")) as source:
        if source.width * source.height > 16_000_000:
            raise ValueError("image_too_large")
        image = ImageOps.fit(ImageOps.exif_transpose(source).convert("RGB"), (720, 680))
        encoded = BytesIO()
        image.save(encoded, format="JPEG", quality=74)
        return encoded.getvalue()


def _build(arguments, files):
    return build_deck(arguments, dict(resolve_input_files(files)))


def build_deck(arguments, available):
    output = BytesIO()
    image_names = {}
    with ZipFile(TEMPLATE) as source, ZipFile(output, "w", ZIP_DEFLATED) as deck:
        presentation = fromstring(source.read("ppt/presentation.xml"))
        presentation.find("p:sldSz", NS).set("type", "screen16x9")
        slide_ids = presentation.find("p:sldIdLst", NS)
        slide_ids.clear()
        rels = _package_manifest(source.read("ppt/_rels/presentation.xml.rels"))
        types = _package_manifest(source.read("[Content_Types].xml"))
        for rel in list(rels):
            if rel.get("Type").endswith("/slide"):
                rels.remove(rel)
        for entry in list(types):
            if entry.get("PartName", "").startswith(("/ppt/slides/", "/ppt/notesSlides/")):
                types.remove(entry)
        slides = [{"title": arguments["title"]}, *arguments["slides"]]
        for page, item in enumerate(slides, start=1):
            image = item.get("image_filename")
            layout = 1 if page == 1 else 3 if image else 2
            fields = {
                "TITLE": item["title"],
                "SUBTITLE": arguments.get("subtitle", ""),
                "PAGE": str(page),
            }
            deck.writestr(
                f"ppt/slides/slide{page}.xml",
                _content(
                    source.read(f"ppt/slides/slide{layout}.xml"), fields, item.get("points", [])
                ),
            )
            deck.writestr(
                f"ppt/notesSlides/notesSlide{page}.xml",
                _content(
                    source.read("ppt/notesSlides/notesSlide1.xml"), {"NOTES": item.get("notes", "")}
                ),
            )
            targets = {"notesSlide": f"../notesSlides/notesSlide{page}.xml"}
            if image:
                if image not in image_names:
                    name = f"image{len(image_names) + 1}.jpeg"
                    deck.writestr(f"ppt/media/{name}", _image(available.get(image)))
                    image_names[image] = name
                targets["image"] = f"../media/{image_names[image]}"
            deck.writestr(
                f"ppt/slides/_rels/slide{page}.xml.rels",
                _relationships(source.read(f"ppt/slides/_rels/slide{layout}.xml.rels"), targets),
            )
            deck.writestr(
                f"ppt/notesSlides/_rels/notesSlide{page}.xml.rels",
                _relationships(
                    source.read("ppt/notesSlides/_rels/notesSlide1.xml.rels"),
                    {"slide": f"../slides/slide{page}.xml"},
                ),
            )
            rid = f"rIdSlide{page}"
            ET.SubElement(
                slide_ids, f"{{{NS['p']}}}sldId", {"id": str(255 + page), f"{{{NS['r']}}}id": rid}
            )
            ET.SubElement(
                rels,
                "Relationship",
                {"Id": rid, "Type": NS["r"] + "/slide", "Target": f"slides/slide{page}.xml"},
            )
            for folder, kind in (("slides", "slide"), ("notesSlides", "notesSlide")):
                ET.SubElement(
                    types,
                    "Override",
                    {
                        "PartName": f"/ppt/{folder}/{kind}{page}.xml",
                        "ContentType": SLIDE_TYPE + kind + "+xml",
                    },
                )
        document = fromstring(source.read("docProps/core.xml"))
        document.find("{*}title").text = _text(arguments["title"])
        stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        document.find("{*}created").text = stamp
        document.find("{*}modified").text = stamp
        app = fromstring(source.read("docProps/app.xml"))
        app.find("{*}Slides").text = str(len(slides))
        app.find("{*}Notes").text = str(sum(bool(slide.get("notes")) for slide in slides))
        app.find("{*}PresentationFormat").text = "16:9"
        app.find("{*}Application").text = "ReMind"
        for field in ("HeadingPairs", "TitlesOfParts"):
            app.remove(app.find("{*}" + field))
        changed = {
            "docProps/core.xml": document,
            "docProps/app.xml": app,
            "ppt/presentation.xml": presentation,
            "ppt/_rels/presentation.xml.rels": rels,
            "[Content_Types].xml": types,
        }
        for path in source.namelist():
            if path.startswith(("ppt/slides/", "ppt/notesSlides/", "ppt/media/")):
                continue
            deck.writestr(path, _xml(changed[path]) if path in changed else source.read(path))
    return output.getvalue()


def create_presentation(
    arguments: dict, files: list[dict], workspace: ArtifactWorkspace
) -> ModelToolResult:
    try:
        result = workspace.save_presentation(arguments["filename"], _build(arguments, files), files)
        result.output["slide_count"] = 1 + len(arguments["slides"])
        result.output["artifact"]["metadata"]["slides"] = [
            {
                "title": arguments["title"],
                "points": [arguments["subtitle"]] if arguments.get("subtitle") else [],
            },
            *[{"title": item["title"], "points": item["points"]} for item in arguments["slides"]],
        ]
        return result
    except ValueError as error:
        code = str(error)
        return ModelToolResult(
            {
                "ok": False,
                "error": code
                if code
                in {
                    "invalid_slide_text",
                    "file_not_available",
                    "image_too_large",
                    "artifact_too_large",
                    "invalid_artifact_filename",
                    "artifact_rate_limit",
                    "workspace_limit_reached",
                }
                else "presentation_creation_failed",
            }
        )
    except (OSError, Image.DecompressionBombError):
        return ModelToolResult({"ok": False, "error": "presentation_creation_failed"})
