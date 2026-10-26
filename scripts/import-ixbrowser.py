"""CLI untuk mengimpor profil dan cookie dari arsip ekspor ixBrowser."""
import argparse
import json
from pathlib import Path
import sys

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from antidetect import iximport  # noqa: E402


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Impor profil dan cookie dari arsip zip ekspor ixBrowser."
    )
    parser.add_argument(
        "--zip",
        dest="zip_path",
        required=True,
        help="Path ke file zip ekspor ixBrowser",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Jalankan impor ke database (tanpa flag ini hanya menampilkan preview)",
    )
    parser.add_argument(
        "--update-existing",
        action="store_true",
        help="Perbarui cookie pada profil dengan nama yang sudah ada",
    )
    args = parser.parse_args(argv)

    try:
        if args.apply:
            result = iximport.apply_import(
                args.zip_path, update_existing=args.update_existing
            )
        else:
            result = iximport.preview(args.zip_path)
    except iximport.IxImportError as error:
        sys.exit(f"error: {error}")

    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
