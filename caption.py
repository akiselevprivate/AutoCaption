import sys

if "LLaVA" not in sys.path:
    sys.path.append("LLaVA")


import os
import subprocess
import time
from pathlib import Path

import requests
import torch
from PIL import Image
from huggingface_hub import hf_hub_download

from llava.constants import DEFAULT_IMAGE_TOKEN, IMAGE_TOKEN_INDEX
from llava.conversation import conv_templates
from llava.mm_utils import tokenizer_image_token
from llava.model.builder import load_pretrained_model
from llava.utils import disable_torch_init

# Hugging Face model repository URLs
HUGGINGFACE_WEIGHTS_URL = "huggingface.co"
# files to download from Hugging Face model repositories
weights = [
    {
        "dest": "liuhaotian/llava-v1.5-13b",
        "src": "liuhaotian/llava-v1.5-13b",
        "files": [
            "config.json",
            "generation_config.json",
            "pytorch_model-00001-of-00003.bin",
            "pytorch_model-00002-of-00003.bin",
            "pytorch_model-00003-of-00003.bin",
            "pytorch_model.bin.index.json",
            "special_tokens_map.json",
            "tokenizer.model",
            "tokenizer_config.json",
        ],
    },
    {
        "dest": "openai/clip-vit-large-patch14-336",
        "src": "openai/clip-vit-large-patch14-336",
        "files": ["config.json", "preprocessor_config.json", "pytorch_model.bin"],
    },
]

PROMPT = """
Write a four sentence caption{ENCODER_PROMPT} for this image. In the first sentence describe the style and type (painting, photo, etc) of the image. Describe in the remaining sentences the contents and composition of the image. Only use language that would be used to prompt a text to image model. Do not include usage. Comma separate keywords rather than using "or". Precise composition is important. Avoid phrases like "conveys a sense of" and "capturing the", just use the terms themselves.

Good examples are:

"Photo of an alien woman with a glowing halo standing on top of a mountain, wearing a white robe and silver mask in the futuristic style with futuristic design, sky background, soft lighting, dynamic pose, a sense of future technology, a science fiction movie scene rendered in the Unreal Engine."

"A scene from the cartoon series Masters of the Universe depicts Man-At-Arms wearing a gray helmet and gray armor with red gloves. He is holding an iron bar above his head while looking down on Orko, a pink blob character. Orko is sitting behind Man-At-Arms facing left on a chair. Both characters are standing near each other, with Orko inside a yellow chestplate over a blue shirt and black pants. The scene is drawn in the style of the Masters of the Universe cartoon series."

"An emoji, digital illustration, playful, whimsical. A cartoon zombie character with green skin and tattered clothes reaches forward with two hands, they have green skin, messy hair, an open mouth and gaping teeth, one eye is half closed."
""".strip()


def download_weights(baseurl: str, basedest: str, files: list[str]):
    base_dir = Path(basedest)
    start = time.time()
    print("downloading to: ", base_dir)
    base_dir.mkdir(parents=True, exist_ok=True)
    for f in files:
        dest = base_dir / f
        # Download files from Hugging Face using hf_hub_download
        if not dest.exists():
            print(f"downloading {f} from Hugging Face")
            file_path = hf_hub_download(repo_id=baseurl, filename=f)
            with open(dest, "wb") as local_file:
                with open(file_path, "rb") as remote_file:
                    local_file.write(remote_file.read())
    print("downloading took: ", time.time() - start)


class Captioner:
    def load_models(self):
        for weight in weights:
            download_weights(weight["src"], weight["dest"], weight["files"])
        disable_torch_init()

        self.tokenizer, self.model, self.image_processor, self.context_len = (
            load_pretrained_model(
                "liuhaotian/llava-v1.5-13b",
                model_name="llava-v1.5-13b",
                model_base=None,
                load_8bit=False,
                load_4bit=False,
            )
        )

    def iter_images_captions(self, image_folder: Path):
        for root, _, files in os.walk(image_folder):
            for filename in files:
                if filename.lower().endswith(
                    (".png", ".jpg", ".jpeg", ".bmp", ".gif", ".webp")
                ):
                    image_path = Path(root) / filename
                    caption_filename = image_path.stem + ".txt"
                    caption_path = image_path.parent / caption_filename
                    yield image_path, caption_path

    def all_images_are_captioned(self, image_folder: Path):
        for _, caption_path in self.iter_images_captions(image_folder):
            if not caption_path.exists():
                return False
        return True

    def caption_images(
        self,
        image_folder: Path,
        autocaption_prefix: str,
        autocaption_suffix: str,
        encoder_prompt: str,
    ):
        for image_path, caption_path in self.iter_images_captions(image_folder):
            if caption_path.exists():
                print(f"{image_path.name} is already captioned")
            else:
                self.caption_image(
                    image_path,
                    caption_path,
                    autocaption_prefix,
                    autocaption_suffix,
                    encoder_prompt,
                )

    def caption_image(
        self,
        image_path: Path,
        caption_path: Path,
        autocaption_prefix: str,
        autocaption_suffix: str,
        encoder_prompt: str,
    ):
        conv_mode = "llava_v1"
        conv = conv_templates[conv_mode].copy()

        image_data = Image.open(image_path).convert("RGB")
        image_tensor = (
            self.image_processor.preprocess(image_data, return_tensors="pt")[
                "pixel_values"
            ]
            .half()
            .cuda()
        )

        # just one turn, always prepend image token
        inp = DEFAULT_IMAGE_TOKEN + "\n"
        inp += PROMPT.replace("{ENCODER_PROMPT}", encoder_prompt)
        if autocaption_prefix != "":
            inp += f"Always start the prompt with exacly these words: {autocaption_prefix}\n"
        if autocaption_suffix != "":
            inp += (
                f"Always end the prompt with exacly these words: {autocaption_suffix}\n"
            )

        conv.append_message(conv.roles[0], inp)

        conv.append_message(conv.roles[1], None)
        prompt = conv.get_prompt()

        input_ids = (
            tokenizer_image_token(
                prompt, self.tokenizer, IMAGE_TOKEN_INDEX, return_tensors="pt"
            )
            .unsqueeze(0)  # pyright: ignore
            .cuda()
        )
        with torch.inference_mode():
            output_ids = self.model.generate(
                inputs=input_ids,
                images=image_tensor,
                do_sample=True,
                temperature=0.2,
                top_p=1.0,
                max_new_tokens=512,
                use_cache=True,
            )
            output = self.tokenizer.batch_decode(output_ids, skip_special_tokens=True)[
                0
            ].strip()

            output = output

            print(f"Caption for {image_path}: {output}")

            caption_path.write_text(output)
