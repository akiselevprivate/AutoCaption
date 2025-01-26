from caption import Captioner
import argparse

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Auto-caption images in a folder.")
    parser.add_argument(
        "image_folder", type=str, help="Path to the folder containing images."
    )
    parser.add_argument(
        "--prefix",
        type=str,
        help="Prefix for the auto-generated captions.",
        default="",
    )
    parser.add_argument(
        "--suffix",
        type=str,
        help="Suffix for the auto-generated captions.",
        default="",
    )

    args = parser.parse_args()

    captioner = Captioner()

    print("Loading models...")

    captioner.load_models()

    print("Captioning images...")

    captioner.caption_images(args.image_folder, args.prefix, args.suffix)

    print("All images captioned.")
