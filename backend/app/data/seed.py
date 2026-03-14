"""
Seed script - Run to import data from Excel into the database.
Usage: python -m app.data.seed [path_to_excel]
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from app.data.importer import import_excel


def main():
    excel_path = sys.argv[1] if len(sys.argv) > 1 else "/data/MaTranKienThuc.xlsx"

    # Fallback paths
    if not os.path.exists(excel_path):
        alt_path = os.path.join(os.path.dirname(__file__), "..", "..", "..", "MaTranKienThuc.xlsx")
        if os.path.exists(alt_path):
            excel_path = alt_path

    if not os.path.exists(excel_path):
        print(f"Error: Excel file not found at '{excel_path}'")
        print("Provide path as: python -m app.data.seed <path>")
        sys.exit(1)

    print(f"Importing from: {excel_path}")
    import_excel(excel_path)


if __name__ == "__main__":
    main()
