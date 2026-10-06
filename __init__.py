"""MarkLayer for ComfyUI: save images with EU AI Act marking (C2PA + invisible watermark + IPTC)."""
if __package__:  # ComfyUI imports this folder as a package
    from .nodes import NODE_CLASS_MAPPINGS, NODE_DISPLAY_NAME_MAPPINGS
else:  # imported as a plain file (pytest collection): nothing to register
    NODE_CLASS_MAPPINGS, NODE_DISPLAY_NAME_MAPPINGS = {}, {}

__all__ = ["NODE_CLASS_MAPPINGS", "NODE_DISPLAY_NAME_MAPPINGS"]
