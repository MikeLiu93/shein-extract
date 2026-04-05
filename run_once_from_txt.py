import argparse
from pathlib import Path

from take_orders_worker import OUTPUT_ROOT, process_order_file


def main():
    p = argparse.ArgumentParser(description="Run one txt order file once.")
    p.add_argument("txt_file", help="Path to txt file containing SHEIN URLs")
    args = p.parse_args()

    txt = Path(args.txt_file).expanduser().resolve()
    if not txt.exists():
        raise SystemExit(f"File not found: {txt}")

    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    ok, msg = process_order_file(txt)
    if ok:
        print(f"Success. Output folder: {msg}")
    else:
        print(f"Failed: {msg}")


if __name__ == "__main__":
    main()

