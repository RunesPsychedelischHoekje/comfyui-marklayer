# MarkLayer for ComfyUI: EU AI Act image marking

A **Save Image** node that marks every image as AI-generated before writing it to disk, the way the
EU AI Act (Article 50(2)) and California's AI Transparency Act ask for:

- **C2PA Content Credentials**: a signed manifest saying the image was created by AI, with your app's name
- **Invisible watermark** (Adobe TrustMark): survives JPEG compression, resizing and social-media uploads
- **IPTC `DigitalSourceType`**: the tag Meta and Google read to show "AI info" labels

Your workflow is still embedded in the PNG, like the built-in Save Image does it.

If you run a generative AI app or service that people in the EU use, you are the "provider" and must
mark outputs in a machine-readable way: since 2 August 2026 for new systems, and by **2 December 2026**
for systems already on the market. That applies even when the underlying model is someone else's.

## Install

**ComfyUI Manager:** search for "MarkLayer" and install.

**Manually:**

```bash
cd ComfyUI/custom_nodes
git clone https://github.com/RunesPsychedelischHoekje/comfyui-marklayer
```

No extra Python packages are needed. Restart ComfyUI.

## Set your API key

The node calls the [MarkLayer API](https://rapidapi.com/RunesPsychedelischHoekje/api/marklayer).
The free plan includes 50 images a month. Subscribe on RapidAPI, copy your key, then **either**:

- set the environment variable `MARKLAYER_API_KEY` before starting ComfyUI, **or**
- copy `config.example.json` to `config.json` in this folder and paste the key in.

The key is deliberately **not** a field on the node: ComfyUI saves every node field into the
metadata of each image it writes, so a key typed into the node would end up inside your images.

## Use

Replace **Save Image** with **Save Image (MarkLayer, EU AI Act)** (under `image/MarkLayer`).

| Field | What it does |
|---|---|
| `filename_prefix` | Same as Save Image. |
| `kind` | `ai_generated` (made by AI) or `ai_edited` (a real image changed with AI: inpainting, img2img). |
| `generator` | Your app's or system's name, recorded in the C2PA manifest. |
| `format` | `png`, `jpeg` or `webp`. |
| `quality` | JPEG/WebP quality. |

The node also outputs the marked images, so you can chain a preview after it.

**Mark before you upscale.** The API accepts images up to 4.5 megapixels (about 2100 x 2100), which
covers normal SD 1.5, SDXL and Flux output. Saving files from other nodes after this one, or
editing the saved file, removes the signed metadata. The watermark stays.

If the API can't be reached, or your quota is used up, the node **stops the workflow with an error**
instead of saving unmarked images.

## Check a result

Upload a saved image to [contentcredentials.org/verify](https://contentcredentials.org/verify) to see
the C2PA manifest. The signer shows as "MarkLayer", not yet on the C2PA trust list, so verifiers
call it unrecognised; the signature itself is valid. Or use MarkLayer's `/v1/inspect` endpoint,
which also reports the watermark and IPTC tag.

## Privacy

Each image is sent to the MarkLayer API (hosted in the EU, Frankfurt), processed in memory and not
stored. The PNG you send includes your workflow metadata, as Save Image would write it. Start
ComfyUI with `--disable-metadata` to leave it out.

MarkLayer adds technical marking. It isn't legal advice or a certificate of compliance.

## Licence

MIT. The MarkLayer API is a paid service with a free plan; see its
[terms](https://rapidapi.com/RunesPsychedelischHoekje/api/marklayer).

## Development

```bash
# needs a local checkout of the MarkLayer API (private) next to this folder, or MARKLAYER_REPO
python -m pytest
```

The tests start the API locally and run the node against it, then inspect the saved files.
