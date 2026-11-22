"""Pack SmartFlow into a zip to share with teammates.

    .venv/bin/python share.py      # writes smartflow.zip next to the project folder

The zip holds the code, the website, the network, the traffic, the trained forecast and the results the website
shows. It leaves out what is big and can be made again: .venv (the setup makes it), SUMO's trip files (1.9 GB,
made by the runs of steps 2 to 5) and the JICA report PDFs (55 MB, linked under "Sources" in README step 2).
A teammate unzips it and follows "Quick start" at the top of README.md.
"""
import os
import zipfile

import live         # the website: it brings out/summary/ up to date, which the statistics page reads

SKIP_DIRS = {".venv", "__pycache__", ".git"}
SKIP_PATHS = ("data/jica/", "data/jica_part2/", "data/jica_2015/")    # the JICA report PDFs
SKIP_ENDINGS = ("_tripinfo.xml", ".pyc", ".DS_Store")


def main():
    for day in live.TEST_DAYS:
        if live.summary(day) is None:
            print(f"Note: {day} has no results, so the statistics page will say so for that day.")
    root = os.path.dirname(os.path.abspath(__file__))
    target = os.path.join(os.path.dirname(root), "smartflow.zip")
    files = size = 0
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as z:
        for folder, dirs, names in os.walk(root):
            dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS)
            for name in sorted(names):
                path = os.path.join(folder, name)
                rel = os.path.relpath(path, root).replace(os.sep, "/")
                if rel.startswith(SKIP_PATHS) or name.endswith(SKIP_ENDINGS) or "_partial_" in name:
                    continue
                z.write(path, f"smartflow/{rel}")
                files += 1
                size += os.path.getsize(path)
    print(f"Wrote {target}: {files} files, {size / 1e6:.1f} MB, {os.path.getsize(target) / 1e6:.1f} MB zipped")


if __name__ == "__main__":
    main()
