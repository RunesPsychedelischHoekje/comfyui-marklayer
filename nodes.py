"""MarkLayer Save Image: a drop-in replacement for ComfyUI's Save Image that marks every image as
AI-generated (EU AI Act Article 50) before it is written to disk.

Why a *save* node and not a filter: C2PA Content Credentials and IPTC metadata live in the file,
not in the pixels. Any node that passes on an IMAGE tensor would lose them when the next node
re-encodes. So this node sends each image to MarkLayer and writes the returned file as-is.
"""
import io
import json
import os

import numpy as np
import torch
from PIL import Image
from PIL.PngImagePlugin import PngInfo

import folder_paths

from .client import MarkLayerError, mark

try:  # honour ComfyUI's --disable-metadata flag, like the built-in Save Image
    from comfy.cli_args import args

    DISABLE_METADATA = bool(getattr(args, "disable_metadata", False))
except Exception:  # pragma: no cover - outside ComfyUI
    DISABLE_METADATA = False

EXTENSIONS = {"png": "png", "jpeg": "jpg", "webp": "webp"}


class MarkLayerSaveImage:
    def __init__(self):
        self.output_dir = folder_paths.get_output_directory()
        self.type = "output"

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "images": ("IMAGE", {"tooltip": "The images to mark and save."}),
                "filename_prefix": ("STRING", {"default": "MarkLayer", "tooltip": "Same as Save Image's prefix."}),
                "kind": (["ai_generated", "ai_edited"], {
                    "default": "ai_generated",
                    "tooltip": "ai_generated: made from scratch by AI. ai_edited: a real image changed with AI (inpainting, img2img).",
                }),
                "generator": ("STRING", {
                    "default": "ComfyUI",
                    "tooltip": "Name of your AI system or app, recorded in the C2PA manifest and XMP CreatorTool.",
                }),
                "format": (["png", "jpeg", "webp"], {"default": "png"}),
                "quality": ("INT", {"default": 92, "min": 50, "max": 100, "tooltip": "JPEG/WebP quality."}),
            },
            "hidden": {"prompt": "PROMPT", "extra_pnginfo": "EXTRA_PNGINFO"},
        }

    RETURN_TYPES = ("IMAGE",)
    RETURN_NAMES = ("marked_images",)
    FUNCTION = "save"
    OUTPUT_NODE = True
    CATEGORY = "image/MarkLayer"
    DESCRIPTION = (
        "Saves images with EU AI Act marking: a signed C2PA manifest, an invisible watermark and the IPTC "
        "'AI-generated' tag, via the MarkLayer API. Needs a MarkLayer API key (see the node's README)."
    )

    def save(self, images, filename_prefix="MarkLayer", kind="ai_generated", generator="ComfyUI",
             format="png", quality=92, prompt=None, extra_pnginfo=None):
        full_output_folder, filename, counter, subfolder, filename_prefix = folder_paths.get_save_image_path(
            filename_prefix, self.output_dir, images[0].shape[1], images[0].shape[0]
        )
        results, marked_tensors = [], []
        for batch_number, image in enumerate(images):
            pil = Image.fromarray(np.clip(255.0 * image.cpu().numpy(), 0, 255).astype(np.uint8))
            png = io.BytesIO()
            # Workflow metadata goes in like Save Image does it; MarkLayer keeps PNG text chunks.
            pil.save(png, "PNG", pnginfo=self._pnginfo(prompt, extra_pnginfo), compress_level=4)
            try:
                data, headers = mark(png.getvalue(), kind=kind, generator=generator.strip(),
                                     output_format=format, quality=quality)
            except MarkLayerError as exc:
                # Fail loudly: silently saving an unmarked image defeats the point of this node.
                raise RuntimeError(str(exc)) from exc

            name = filename.replace("%batch_num%", str(batch_number))
            file = f"{name}_{counter:05}_.{EXTENSIONS[format]}"
            with open(os.path.join(full_output_folder, file), "wb") as f:
                f.write(data)  # written byte-for-byte: re-encoding would break the C2PA signature
            results.append({"filename": file, "subfolder": subfolder, "type": self.type})
            wid = headers.get("x-watermark-id")
            print(f"[MarkLayer] saved {file} (watermark {wid}, layers {headers.get('x-layers')})")

            out = Image.open(io.BytesIO(data)).convert("RGB")
            marked_tensors.append(torch.from_numpy(np.asarray(out).astype(np.float32) / 255.0))
            counter += 1

        return {"ui": {"images": results}, "result": (torch.stack(marked_tensors),)}

    @staticmethod
    def _pnginfo(prompt, extra_pnginfo) -> PngInfo | None:
        if DISABLE_METADATA:
            return None
        info = PngInfo()
        if prompt is not None:
            info.add_text("prompt", json.dumps(prompt))
        for key, value in (extra_pnginfo or {}).items():
            info.add_text(key, json.dumps(value))
        return info


NODE_CLASS_MAPPINGS = {"MarkLayerSaveImage": MarkLayerSaveImage}
NODE_DISPLAY_NAME_MAPPINGS = {"MarkLayerSaveImage": "Save Image (MarkLayer, EU AI Act)"}
